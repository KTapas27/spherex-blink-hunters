"""Probe SPHEREx coverage for the challenge test targets.

For each target: look up proper motion/parallax via CDS Sesame, move the position
to the SPHEREx era, then count the DR1 + QR3 spectral images that cover it,
split by detector and by observing "visit" (clusters of dates).
"""
import logging
import time
import urllib.parse
import warnings
import xml.etree.ElementTree as ET

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import Distance, SkyCoord
from astropy.time import Time
from astroquery.ipac.irsa import Irsa

logging.getLogger("astropy").setLevel(logging.ERROR)
warnings.filterwarnings("ignore")

TARGETS = {
    "Barnard's Star": "Barnard's Star",
    "Epsilon Indi B": "eps Ind B",
    "WISE 0855": "WISE J085510.83-071442.5",
    "RW Aurigae": "RW Aur",
    "R Draconis": "R Dra",
}
COLLECTIONS = ["spherex_dr1", "spherex_qr3"]
SPHEREX_EPOCH = Time("2026-01-01")
VISIT_GAP_DAYS = 30

def sesame(name):
    """CDS Sesame name resolver; returns J2000 ra/dec plus pm and parallax when known."""
    url = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?" + urllib.parse.quote(name)
    root = ET.fromstring(requests.get(url, timeout=40).content)
    res = root.find(".//Resolver")

    def num(tag):
        el = res.find(tag)
        return float(el.text) if el is not None and el.text else None

    plx_el = res.find("plx/v")
    return dict(ra=num("jradeg"), dec=num("jdedeg"), pmra=num("pm/pmRA") or 0.0,
                pmdec=num("pm/pmDE") or 0.0,
                plx=float(plx_el.text) if plx_el is not None else None)


def resolve(name):
    row = sesame(name)
    pmra, pmdec, plx = row["pmra"], row["pmdec"], row["plx"]
    kwargs = dict(ra=row["ra"] * u.deg, dec=row["dec"] * u.deg,
                  pm_ra_cosdec=pmra * u.mas / u.yr, pm_dec=pmdec * u.mas / u.yr,
                  obstime=Time("J2000"))
    if plx and plx > 0:
        kwargs["distance"] = Distance(parallax=plx * u.mas)
    c2000 = SkyCoord(**kwargs)
    now = c2000.apply_space_motion(new_obstime=SPHEREX_EPOCH)
    return c2000, now, pmra, pmdec, plx


def visits(mjds):
    mjds = np.sort(np.asarray(mjds))
    groups, start = [], 0
    for i in range(1, len(mjds) + 1):
        if i == len(mjds) or mjds[i] - mjds[i - 1] > VISIT_GAP_DAYS:
            groups.append(mjds[start:i])
            start = i
    return groups


for label, name in TARGETS.items():
    print(f"\n=== {label} ({name}) ===")
    try:
        c2000, now, pmra, pmdec, plx = resolve(name)
    except Exception as exc:  # SIMBAD hiccups shouldn't stop the survey
        print("  SIMBAD lookup failed:", exc)
        continue
    shift = c2000.separation(now).to(u.arcsec)
    print(f"  J2000 {c2000.to_string('hmsdms', precision=1)}")
    print(f"  pm = ({pmra:.0f}, {pmdec:.0f}) mas/yr, parallax = {plx} mas")
    print(f"  moved {shift:.1f} (= {shift.value / 6.15:.1f} SPHEREx pixels) from J2000 to 2026.0")

    t0 = time.time()
    res = Irsa.query_sia(pos=(SkyCoord(now.ra, now.dec), 1 * u.arcsec), collection=COLLECTIONS)
    tab = res.to_table() if hasattr(res, "to_table") else res
    print(f"  SIA: {len(tab)} images in {time.time() - t0:.1f} s")
    if len(tab) == 0:
        continue

    for coll in np.unique(tab["obs_collection"]):
        print(f"    collection {coll}: {np.sum(tab['obs_collection'] == coll)}")
    dets = sorted(np.unique(tab["energy_bandpassname"]))
    print("  per detector:", {d: int(np.sum(tab["energy_bandpassname"] == d)) for d in dets})

    groups = visits(tab["t_min"])
    for g in groups:
        span = f"{Time(g.min(), format='mjd').iso[:10]} .. {Time(g.max(), format='mjd').iso[:10]}"
        print(f"    visit {span}: {len(g)} images")
    est_mb = np.nansum(np.asarray(tab["access_estsize"], dtype=float)) / 1024
    print(f"  full-image download if fetched whole: {est_mb / 1024:.1f} GB")
