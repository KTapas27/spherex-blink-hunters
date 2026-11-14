"""Download small pixel stamps around a target from each SPHEREx exposure.

Primary route: read only the needed rows from the public AWS S3 copy (skips the
~4-5 MB PSF cube). Fallback: the IRSA cutout service.
"""
import concurrent.futures
import logging
import time
import warnings

import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.utils.data import conf
from astropy.wcs import WCS

from . import config

logging.getLogger("astropy").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", module="astropy")
conf.remote_timeout = config.REMOTE_TIMEOUT_S
log = logging.getLogger(__name__)

LAYERS = ("IMAGE", "FLAGS", "VARIANCE", "ZODI")
FULL_SIZE = 2040


def _stamp_from_hdul(hdul, coord, half, sliced):
    header = hdul["IMAGE"].header
    wcs = WCS(header)
    x, y = (float(v) for v in wcs.world_to_pixel(coord))
    if sliced:
        nx = ny = FULL_SIZE
        xi, yi = int(round(x)), int(round(y))
        if not (-half <= xi < nx + half and -half <= yi < ny + half):
            return None
        y0, y1 = max(yi - half, 0), min(yi + half + 1, ny)
        x0, x1 = max(xi - half, 0), min(xi + half + 1, nx)
        if y1 - y0 < 3 or x1 - x0 < 3:
            return None
        arrays = {name.lower(): np.array(hdul[name].section[y0:y1, x0:x1]) for name in LAYERS}
        stamp_wcs = wcs[y0:y1, x0:x1]
    else:
        y0 = x0 = 0
        arrays = {name.lower(): np.array(hdul[name].data) for name in LAYERS}
        stamp_wcs = wcs

    spectral = WCS(header, fobj=hdul, key="W")
    spectral.sip = None
    yy, xx = np.indices(arrays["image"].shape)
    wave, _ = spectral.pixel_to_world(xx + x0, yy + y0)
    arrays["wave"] = np.asarray(wave.to_value("um"), dtype=np.float32)
    arrays["header"] = np.array(stamp_wcs.to_header(relax=True).tostring())
    return arrays


def _fetch_s3(exp, coord, half):
    with fits.open(exp.s3_path, use_fsspec=True, fsspec_kwargs=config.S3_FSSPEC_KWARGS,
                   lazy_load_hdus=True) as hdul:
        return _stamp_from_hdul(hdul, coord, half, sliced=True)


def _fetch_cutout(exp, coord, half):
    size_deg = (2 * half + 1) * config.PIXEL_SCALE_ARCSEC / 3600
    url = f"{exp.access_url}?center={coord.ra.deg},{coord.dec.deg}d&size={size_deg:.4f}"
    with fits.open(url, cache=False) as hdul:
        return _stamp_from_hdul(hdul, coord, half, sliced=False)


def stamp_path(exp, ra, dec, half):
    return config.STAMP_DIR / f"{exp.key}_{ra:.5f}_{dec:.5f}_{half}.npz"


def get_stamp(exp, ra, dec, half):
    """Return the cached stamp dict for one exposure, downloading it if needed."""
    path = stamp_path(exp, ra, dec, half)
    if path.exists():
        with np.load(path) as data:
            return {k: data[k] for k in data.files} or None
    coord = SkyCoord(ra, dec, unit="deg")
    routes = ([_fetch_s3] if exp.s3_path else []) + [_fetch_cutout]
    last_err = None
    for attempt in range(config.FETCH_RETRIES):
        route = routes[min(attempt, len(routes) - 1)]
        try:
            stamp = route(exp, coord, half)
            path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(path, **(stamp or {}))
            return stamp
        except Exception as err:  # network errors vary a lot; retry, then fall back
            last_err = err
            time.sleep(1 + 2 * attempt)
    log.warning("giving up on %s: %s", exp.key, last_err)
    return None


def get_stamps(exposures, ra, dec, half, progress=None):
    """Fetch stamps in parallel. `progress(done, total)` is called as they complete."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as pool:
        futures = {pool.submit(get_stamp, e, ra, dec, half): e for e in exposures}
        for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
            exp = futures[fut]
            stamp = fut.result()
            if stamp:
                results[exp.key] = stamp
            if progress:
                progress(i, len(exposures))
    return results
