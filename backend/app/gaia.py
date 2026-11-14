"""Gaia DR3 sources for a view, moved to the SPHEREx epoch, in view pixel coordinates.

Uses IRSA's indexed cone search (fast), falling back to MAST; ESA and CDS were slow or
unreachable during development.
"""
import json

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


def sources_for_view(view_dir, manifest):
    cache = view_dir / "gaia.json"
    if cache.exists():
        return json.loads(cache.read_text())
    t = manifest["target"]
    fov = manifest["fov_deg"]
    centre, radius = SkyCoord(t["ra"], t["dec"], unit="deg"), fov * 0.75 * u.deg
    try:
        tab = Irsa.query_region(centre, catalog="gaia_dr3_source", spatial="Cone", radius=radius,
                                columns="source_id,ra,dec,pmra,pmdec,parallax,phot_g_mean_mag")
    except Exception:  # IRSA busy: same Gaia DR3 columns from MAST
        tab = Catalogs.query_region(centre, radius=radius, catalog="Gaia", version=3)
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
