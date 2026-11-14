"""IRSA tutorial: Download a collection of SPHEREx Spectral Image cutouts.

Follows https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts/
(M101, detector D2, 0.1 deg cutouts), with timing/memory reporting added.
"""
import concurrent.futures
import http.client
import logging
import os
import resource
import time
import urllib.error

import astropy.units as u
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.utils.data import conf
from astropy.visualization import ImageNormalize, AsinhStretch, ZScaleInterval
from astropy.wcs import WCS
from astroquery.ipac.irsa import Irsa

logging.getLogger("astropy").setLevel(logging.ERROR)
conf.remote_timeout = 120

OUT = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUT, exist_ok=True)

coord = SkyCoord(ra=210.80227 * u.degree, dec=54.34895 * u.degree, frame="icrs")
size = 0.1 * u.degree
bandpass = "SPHEREx-D2"

query = f"""
SELECT
    'https://irsa.ipac.caltech.edu/' || a.uri || '?center={coord.ra.deg},{coord.dec.deg}d&size={size.value}' AS uri,
    p.time_bounds_lower
FROM spherex.artifact a
JOIN spherex.plane p ON a.planeid = p.planeid
WHERE 1 = CONTAINS(POINT('ICRS', {coord.ra.deg}, {coord.dec.deg}), p.poly)
        AND p.energy_bandpassname = '{bandpass}'
ORDER BY p.time_bounds_lower
"""

t0 = time.time()
results = Irsa.query_tap(query)
print(f"TAP query: {time.time() - t0:.1f} s, {len(results)} images found")


def process_cutout(row, coord, cache):
    with fits.open(row["uri"], cache=cache) as hdulist:
        header = hdulist[1].header
        spatial_wcs = WCS(header)
        x, y = spatial_wcs.world_to_pixel(coord)
        spectral_wcs = WCS(header, fobj=hdulist, key="W")
        spectral_wcs.sip = None
        wavelength, bandwidth = spectral_wcs.pixel_to_world(x, y)
        row["central_wavelength"] = wavelength.to(u.micrometer).value
        row["version"] = hdulist[0].header.get("VERSION", "")
        hdus = []
        for hdu in hdulist[1:]:
            hdu.header["EXTNAME"] = f"{hdu.header['EXTNAME']}{row['cutout_index']}"
            hdus.append(hdu.copy())
        row["hdus"] = hdus


def process_cutout_with_error_handling(row, coord, cache):
    try:
        process_cutout(row, coord, cache=cache)
    except (TimeoutError, urllib.error.HTTPError, http.client.IncompleteRead,
            http.client.RemoteDisconnected):
        row["hdus"] = None


table = results.to_table()
table["cutout_index"] = range(1, len(table) + 1)
table["central_wavelength"] = np.full(len(table), np.nan)
table["version"] = np.full(len(table), "", dtype="U32")
table["hdus"] = np.full(len(table), None)

t0 = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_cutout_with_error_handling, row, coord, False)
               for row in table]
    concurrent.futures.wait(futures)
elapsed = time.time() - t0

failed = table[table["hdus"] == None]  # noqa: E711
table = table[table["hdus"] != None]  # noqa: E711
print(f"Parallel cutouts: {elapsed:.1f} s, {len(table)} ok, {len(failed)} failed")

# Package as one multi-extension FITS file, as in the tutorial.
cols = fits.ColDefs([
    fits.Column(name="cutout_index", format="J", array=table["cutout_index"]),
    fits.Column(name="observation_date", format="D", array=table["time_bounds_lower"], unit="d"),
    fits.Column(name="central_wavelength", format="D", array=table["central_wavelength"], unit="um"),
    fits.Column(name="version", format="A32", array=table["version"]),
])
table_hdu = fits.BinTableHDU.from_columns(cols)
table_hdu.header["EXTNAME"] = "CUTOUT_INFO"
mef_path = os.path.join(OUT, "spherex_cutouts_mef.fits")
hdus = [fits.PrimaryHDU(), table_hdu] + [h for row_hdus in table["hdus"] for h in row_hdus]
fits.HDUList(hdus).writeto(mef_path, overwrite=True)
print(f"MEF written: {os.path.getsize(mef_path) / 1e6:.1f} MB")

# Plot up to 10 cutouts with their central wavelength and date.
n = min(10, len(table))
fig, axes = plt.subplots(2, 5, figsize=(15, 6.5))
for ax, row in zip(axes.flat, table[:n]):
    img = row["hdus"][0].data
    norm = ImageNormalize(img, interval=ZScaleInterval(), stretch=AsinhStretch())
    ax.imshow(img, origin="lower", cmap="gray", norm=norm)
    ax.set_title(f"{row['central_wavelength']:.3f} µm\nMJD {row['time_bounds_lower']:.1f}", fontsize=9)
    ax.axis("off")
for ax in axes.flat[n:]:
    ax.axis("off")
fig.suptitle("SPHEREx D2 cutouts of M101 (tutorial 1)")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "01_cutouts_grid.png"), dpi=110)

peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
print(f"Peak memory: {peak_mb:.0f} MB")
