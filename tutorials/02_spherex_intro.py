"""IRSA tutorial: Introduction to SPHEREx Spectral Images.

Follows https://caltech-ipac.github.io/irsa-tutorials/spherex-intro/
with the Firefly web viewer swapped for saved matplotlib figures, and
timing/memory reporting added.
"""
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

coord = SkyCoord(304.693508808, 42.4436872991, unit="deg")
search_radius = 1 * u.arcsec

print("SPHEREx SIA collections:",
      list(Irsa.list_collections(servicetype="SIA", filter="spherex")["collection"]))

t0 = time.time()
results = Irsa.query_sia(pos=(coord, search_radius), collection="spherex_qr2")
print(f"SIA query (spherex_qr2): {time.time() - t0:.1f} s, {len(results)} images")

spectral_image_url = results["access_url"][0]
print("First image:", spectral_image_url)

# Download one full (uncut) spectral image, retrying transient errors.
t0 = time.time()
for attempt in range(3):
    try:
        with fits.open(spectral_image_url, memmap=False, cache=False) as hdulist:
            for hdu in hdulist:
                hdu.data
        break
    except (TimeoutError, urllib.error.HTTPError, http.client.IncompleteRead):
        if attempt == 2:
            raise
        time.sleep(10 * (attempt + 1))
print(f"Full image download: {time.time() - t0:.1f} s")
hdulist.info()

header = hdulist["IMAGE"].header
for key in ["NAXIS1", "NAXIS2", "BUNIT", "DETECTOR", "OBSID", "DATE", "PSF_FWHM"]:
    print(f"  {key}: {header.get(key)}")

# Spatial and spectral WCS at the image centre.
wcs = WCS(header)
ra, dec = wcs.wcs.crval
x, y = wcs.world_to_pixel(SkyCoord(ra=ra, dec=dec, unit="deg"))
spectral_wcs = WCS(header=header, fobj=hdulist, key="W")
spectral_wcs.sip = None
wl, bw = spectral_wcs.pixel_to_world(x, y)
print(f"Centre pixel wavelength: {wl:.4f}, bandwidth: {bw:.4f}")

# Wavelength across the whole detector.
yy, xx = np.indices(hdulist["IMAGE"].shape)
wavelength, bandwidth = spectral_wcs.pixel_to_world(xx, yy)
print(f"Wavelength range on this detector: {wavelength.min():.3f} - {wavelength.max():.3f}")

print("Flag counts:")
for card in header.cards:
    if card.keyword.startswith("L2 N_"):
        print(f"  {card.keyword[5:]:<12} {card.value}")

# Figure: zodi-subtracted image, wavelength map, flagged pixels.
image = hdulist["IMAGE"].data - hdulist["ZODI"].data
flags = hdulist["FLAGS"].data
# Bits worth hiding in a viewer (everything except SOURCE=21 and FULLSAMPLE=12).
bad_bits = sum(1 << b for b in (0, 1, 2, 4, 5, 6, 7, 9, 10, 11, 14, 15, 17, 19))
bad = (flags & bad_bits) != 0

fig, axes = plt.subplots(1, 3, figsize=(18, 6))
norm = ImageNormalize(image, interval=ZScaleInterval(), stretch=AsinhStretch())
axes[0].imshow(image, origin="lower", cmap="gray", norm=norm)
axes[0].set_title(f"IMAGE − ZODI (detector {header['DETECTOR']})")
im = axes[1].imshow(wavelength.value, origin="lower", cmap="viridis")
fig.colorbar(im, ax=axes[1], label="Wavelength [µm]")
axes[1].set_title("Per-pixel wavelength (linear variable filter)")
axes[2].imshow(bad, origin="lower", cmap="Reds")
axes[2].set_title(f"Problem-flagged pixels: {bad.sum():,} of {bad.size:,}")
for ax in axes:
    ax.set_xticks([])
    ax.set_yticks([])
fig.tight_layout()
fig.savefig(os.path.join(OUT, "02_intro_image_wavelength_flags.png"), dpi=90)

peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
print(f"Peak memory: {peak_mb:.0f} MB")
