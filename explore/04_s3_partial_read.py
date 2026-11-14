"""Compare two ways of getting a small SPHEREx stamp around a target.

A) IRSA cutout service (?center=..&size=..): always returns the PSF cube too (~5 MB).
B) Public AWS S3 bucket via fsspec: read only the pixel rows we need from
   IMAGE/FLAGS/VARIANCE/ZODI plus the tiny WCS-WAVE table, skipping the PSF.
"""
import json
import logging
import time
import urllib.request
import warnings

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.utils.data import conf
from astropy.wcs import WCS
from astroquery.ipac.irsa import Irsa

logging.getLogger("astropy").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")
conf.remote_timeout = 120

# Barnard's Star moved to 2026.0 (from 03_probe_targets.py).
coord = SkyCoord(269.4486, 4.7684, unit="deg")
HALF = 30  # 61 x 61 pixel stamp ~ 0.1 deg

res = Irsa.query_sia(pos=(coord, 1 * u.arcsec), collection="spherex_dr1")
row = res[0]
cloud = json.loads(row["cloud_access"])["aws"]
s3_path = f"s3://{cloud['bucket_name']}/{cloud['key']}"
print("image:", row["obs_id"], row["energy_bandpassname"])
print("s3:", s3_path)

# A) Cutout service
url = f"{row['access_url']}?center={coord.ra.deg},{coord.dec.deg}d&size=0.1"
t0 = time.time()
with urllib.request.urlopen(url, timeout=120) as r:
    nbytes = len(r.read())
print(f"A) cutout service: {nbytes / 1e6:.2f} MB in {time.time() - t0:.1f} s")

# B) S3 partial read
t0 = time.time()
with fits.open(s3_path, use_fsspec=True, fsspec_kwargs={"anon": True, "default_block_size": 2**18,
                                                       "default_cache_type": "bytes"},
               lazy_load_hdus=True) as hdul:
    header = hdul["IMAGE"].header
    x, y = WCS(header).world_to_pixel(coord)
    x, y = int(round(float(x))), int(round(float(y)))
    ys, xs = slice(max(y - HALF, 0), y + HALF + 1), slice(max(x - HALF, 0), x + HALF + 1)
    stamps = {name: hdul[name].section[ys, xs] for name in ("IMAGE", "FLAGS", "VARIANCE", "ZODI")}
    wave = hdul["WCS-WAVE"].data
print(f"B) S3 partial read: stamp {stamps['IMAGE'].shape} at pixel ({x}, {y}) in {time.time() - t0:.1f} s")
print("   WCS-WAVE rows:", len(wave))
