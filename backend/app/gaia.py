"""Gaia DR3 sources for a view, moved to the SPHEREx epoch, in view pixel coordinates.

IRSA's indexed cone search and MAST are queried at the same time and the first answer wins:
either one can be slow (IRSA took ~100 s from the UAE during testing) and ESA/CDS were often
unreachable. Results are cached per view, and pipeline.py starts the query as soon as a view
is built, so the overlay is usually ready before anyone ticks the box.
"""
import concurrent.futures
import json
import logging
import threading

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astroquery.ipac.irsa import Irsa
from astroquery.mast import Catalogs

from . import config
from .frames import grid_wcs

GAIA_EPOCH = 2016.0
MAX_SOURCES = 600
FAST_PM_MAS = 100  # highlight sources moving faster than this
QUERY_TIMEOUT_S = 90  # give up if neither IRSA nor MAST has answered by then

log = logging.getLogger(__name__)
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="gaia")
_view_locks = {}
_locks_guard = threading.Lock()

COLUMNS = "source_id,ra,dec,pmra,pmdec,parallax,phot_g_mean_mag"


def _from_irsa(centre, radius):
    return Irsa.query_region(centre, catalog="gaia_dr3_source", spatial="Cone", radius=radius, columns=COLUMNS)


def _from_mast(centre, radius):
    return Catalogs.query_region(centre, radius=radius, catalog="Gaia", version=3)


def _query(centre, radius):
    """Ask IRSA and MAST in parallel; return the first table that arrives without error."""
    futures = {_pool.submit(_from_irsa, centre, radius): "IRSA", _pool.submit(_from_mast, centre, radius): "MAST"}
    errors = []
    try:
        for fut in concurrent.futures.as_completed(futures, timeout=QUERY_TIMEOUT_S):
            try:
                tab = fut.result()
            except Exception as err:  # network errors vary; try the other service
                errors.append(f"{futures[fut]}: {err}")
                continue
            log.info("Gaia DR3 from %s: %d rows", futures[fut], len(tab))
            return tab
    except concurrent.futures.TimeoutError:
        errors.append(f"no answer within {QUERY_TIMEOUT_S} s")
    raise RuntimeError("Gaia query failed (" + "; ".join(errors) + ")")


def _lock_for(view_dir):
    with _locks_guard:
        return _view_locks.setdefault(str(view_dir), threading.Lock())


def prefetch(view_dir, manifest):
    """Start fetching Gaia for a view in the background (errors are only logged)."""
    def run():
        try:
            sources_for_view(view_dir, manifest)
        except Exception as err:
            log.warning("Gaia prefetch for %s failed: %s", view_dir.name, err)
    _pool.submit(run)


def sources_for_view(view_dir, manifest):
    cache = view_dir / "gaia.json"
    if cache.exists():
        return json.loads(cache.read_text())
    with _lock_for(view_dir):  # the prefetch and a user click must not query twice
        if cache.exists():
            return json.loads(cache.read_text())
        return _build(view_dir, manifest, cache)


def _build(view_dir, manifest, cache):
    t = manifest["target"]
    fov = manifest["fov_deg"]
    centre, radius = SkyCoord(t["ra"], t["dec"], unit="deg"), fov * 0.75 * u.deg
    tab = _query(centre, radius)
    tab = tab[np.isfinite(np.asarray(tab["phot_g_mean_mag"], dtype=float))]
    tab.sort("phot_g_mean_mag")
    tab = tab[:MAX_SOURCES]

    dt = Time(config.VIEW_EPOCH).jyear - GAIA_EPOCH
    pmra = np.nan_to_num(np.asarray(tab["pmra"], dtype=float))
    pmdec = np.nan_to_num(np.asarray(tab["pmdec"], dtype=float))
    dec0 = np.asarray(tab["dec"], dtype=float)
    ra_now = np.asarray(tab["ra"], dtype=float) + pmra * dt / 3.6e6 / np.cos(np.radians(dec0))
    dec_now = dec0 + pmdec * dt / 3.6e6

    w, shape = grid_wcs(t["ra"], t["dec"], fov)
    x, y = w.world_to_pixel(SkyCoord(ra_now, dec_now, unit="deg"))
    # Where the source sits one year later, for drawing motion arrows.
    x1, y1 = w.world_to_pixel(SkyCoord(ra_now + pmra / 3.6e6 / np.cos(np.radians(dec_now)),
                                       dec_now + pmdec / 3.6e6, unit="deg"))
    out = []
    for i in range(len(tab)):
        if not (-1 <= x[i] <= shape[1] and -1 <= y[i] <= shape[0]):
            continue
        pm = float(np.hypot(pmra[i], pmdec[i]))
        plx = tab["parallax"][i]
        out.append(dict(
            id=str(tab["source_id"][i]), x=float(x[i]), y=float(y[i]),
            dx_per_yr=float(x1[i] - x[i]), dy_per_yr=float(y1[i] - y[i]),
            g=round(float(tab["phot_g_mean_mag"][i]), 2), pm=round(pm, 1),
            parallax=None if np.ma.is_masked(plx) or not np.isfinite(plx) else round(float(plx), 2),
            fast=pm >= FAST_PM_MAS,
        ))
    cache.write_text(json.dumps(out))
    return out
