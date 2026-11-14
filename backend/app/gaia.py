"""Gaia DR3 sources for a view, moved to the SPHEREx epoch, in view pixel coordinates.

Three services that all serve Gaia DR3 are asked at the same time (IRSA, ESA's Gaia archive and
CDS VizieR) and the first answer wins: any of them can be slow or down (IRSA took ~100 s from the
UAE during testing). Only if all three fail is MAST used; MAST offers Gaia DR2 only, whose
positions are for epoch 2015.5, so those are moved from 2015.5 instead of 2016.0 (for Barnard's
Star that half-year is 5 arcsec). Results are cached per view, and pipeline.py starts the query as
soon as a view is built, so the overlay is usually ready before anyone ticks the box.
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

GAIA_EPOCH = 2016.0      # reference epoch of Gaia DR3 positions
GAIA_DR2_EPOCH = 2015.5  # reference epoch of Gaia DR2 positions (MAST fallback)
MAX_SOURCES = 600
FAST_PM_MAS = 100  # highlight sources moving faster than this
QUERY_TIMEOUT_S = 75     # wait this long for any DR3 service before trying MAST
MAST_TIMEOUT_S = 30

log = logging.getLogger(__name__)
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="gaia")
_view_locks = {}
_locks_guard = threading.Lock()

COLUMNS = "source_id,ra,dec,pmra,pmdec,parallax,phot_g_mean_mag"


def _from_irsa(centre, radius):
    return Irsa.query_region(centre, catalog="gaia_dr3_source", spatial="Cone", radius=radius, columns=COLUMNS)


def _from_esa(centre, radius):
    from astroquery.gaia import Gaia  # imported here: it sets up a TAP client on import
    Gaia.MAIN_GAIA_TABLE = "gaiadr3.gaia_source"
    Gaia.ROW_LIMIT = -1
    job = Gaia.cone_search_async(centre, radius=radius, columns=COLUMNS.split(","))
    return job.get_results()


def _from_vizier(centre, radius):
    from astroquery.vizier import Vizier
    names = {"Source": "source_id", "RA_ICRS": "ra", "DE_ICRS": "dec", "pmRA": "pmra", "pmDE": "pmdec",
             "Plx": "parallax", "Gmag": "phot_g_mean_mag"}  # I/355/gaiadr3: RA_ICRS/DE_ICRS at epoch 2016.0
    res = Vizier(columns=list(names), row_limit=-1).query_region(centre, radius=radius, catalog="I/355/gaiadr3")
    if not len(res):
        raise RuntimeError("VizieR returned no table")
    tab = res[0]
    for old_name, new_name in names.items():
        tab.rename_column(old_name, new_name)
    return tab


def _from_mast_dr2(centre, radius):
    return Catalogs.query_region(centre, radius=radius, catalog="Gaia", version=2)


DR3_SERVICES = {"IRSA": _from_irsa, "ESA": _from_esa, "VizieR": _from_vizier}


def _first(services, centre, radius, timeout, errors):
    futures = {_pool.submit(fn, centre, radius): name for name, fn in services.items()}
    try:
        for fut in concurrent.futures.as_completed(futures, timeout=timeout):
            try:
                tab = fut.result()
            except Exception as err:  # network errors vary; wait for the others
                errors.append(f"{futures[fut]}: {str(err).splitlines()[0][:120] if str(err) else type(err).__name__}")
                continue
            return tab, futures[fut]
    except concurrent.futures.TimeoutError:
        errors.append(f"{'/'.join(services)}: no answer within {timeout} s")
    return None, None


def _query(centre, radius):
    """Return (table, reference epoch, release label) from the first service that answers.

    The DR3 services race each other; MAST (DR2) is only asked if none of them answer.
    """
    errors = []
    tab, name = _first(DR3_SERVICES, centre, radius, QUERY_TIMEOUT_S, errors)
    if tab is not None:
        log.info("Gaia DR3 from %s: %d rows", name, len(tab))
        return tab, GAIA_EPOCH, f"Gaia DR3 ({name})"
    tab, name = _first({"MAST": _from_mast_dr2}, centre, radius, MAST_TIMEOUT_S, errors)
    if tab is not None:
        log.warning("Gaia DR3 services failed (%s); using Gaia DR2 from MAST", "; ".join(errors))
        return tab, GAIA_DR2_EPOCH, "Gaia DR2 (MAST)"
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
    tab, epoch, release = _query(centre, radius)
    tab = tab[np.isfinite(np.asarray(tab["phot_g_mean_mag"], dtype=float))]
    tab.sort("phot_g_mean_mag")
    tab = tab[:MAX_SOURCES]

    dt = Time(config.VIEW_EPOCH).jyear - epoch
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
            fast=pm >= FAST_PM_MAS, release=release,
        ))
    cache.write_text(json.dumps(out))
    return out
