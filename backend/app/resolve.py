"""Turn user input (a name or coordinates) into a sky position at the SPHEREx epoch."""
from __future__ import annotations  # allows `X | None` type hints on Python 3.9

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict

import astropy.units as u
import numpy as np
import requests
from astropy.coordinates import Distance, SkyCoord
from astropy.time import Time

from . import config


@dataclass
class Target:
    query: str
    name: str
    ra: float  # degrees, at config.VIEW_EPOCH
    dec: float
    ra_j2000: float
    dec_j2000: float
    pmra: float  # mas/yr (includes cos dec)
    pmdec: float
    parallax: float | None  # mas
    moved_arcsec: float  # J2000 -> VIEW_EPOCH
    note: str = ""  # e.g. "coordinates matched to a known fast-moving object"

    def as_dict(self):
        return asdict(self)


_COORD_RE = re.compile(r"^[\d\s:hmsd.+\-,°'\"]+$")

# Catalogue values for the challenge test targets (SIMBAD via Sesame, Nov 2026), so the
# demo works even when CDS is down. J2000 position, pm in mas/yr, parallax in mas.
KNOWN = {
    "barnard's star": dict(name="NAME Barnard's star", ra=269.4520769586187, dec=4.69336496657667,
                           pmra=-801.551, pmdec=10362.394, parallax=546.9759),
    "eps ind b": dict(name="* eps Ind B", ra=331.04414658852124, dec=-56.78284419511611,
                      pmra=3981.977, pmdec=-2466.832, parallax=270.658),
    "wise j085510.83-071442.5": dict(name="WISEA J085510.74-071442.5", ra=133.81890825, dec=-7.247048,
                                     pmra=-8123.7, pmdec=673.2, parallax=439.0,
                                     hint="It is faint and only glows at 4-5 µm: choose 'all' exposures and "
                                          "the Colour or D6 view to see it."),
    "rw aur": dict(name="V* RW Aur", ra=76.95652603458, dec=30.40143817389,
                   pmra=7.23, pmdec=-20.33, parallax=15.42),
    "r dra": dict(name="V* R Dra", ra=248.16761083295, dec=66.75497941722,
                  pmra=-20.643, pmdec=6.149, parallax=1.2509),
}
_RESOLVE_CACHE = config.CACHE_DIR / "resolved.json"


def _cached_sesame(name):
    key = " ".join(name.lower().split())
    if key in KNOWN:
        return KNOWN[key]
    try:
        cache = json.loads(_RESOLVE_CACHE.read_text())
    except (OSError, ValueError):
        cache = {}
    if key not in cache:
        cache[key] = _sesame(name)
        _RESOLVE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _RESOLVE_CACHE.write_text(json.dumps(cache, indent=1))
    return cache[key]


def _sesame(name):
    url = config.SESAME_URL + urllib.parse.quote(name)
    root = ET.fromstring(requests.get(url, timeout=20).content)
    res = root.find(".//Resolver")
    if res is None or res.find("jradeg") is None:
        raise LookupError(f"Could not resolve '{name}'")

    def num(tag):
        el = res.find(tag)
        return float(el.text) if el is not None and el.text else None

    oname = res.find("oname")
    return dict(
        name=oname.text if oname is not None else name,
        ra=num("jradeg"), dec=num("jdedeg"),
        pmra=num("pm/pmRA") or 0.0, pmdec=num("pm/pmDE") or 0.0,
        parallax=num("plx/v"),
    )


def _parse_coords(text):
    text = text.replace(",", " ").strip()
    parts = text.split()
    if len(parts) == 2 and all(re.fullmatch(r"[+\-]?\d+(\.\d*)?", p) for p in parts):
        return SkyCoord(float(parts[0]), float(parts[1]), unit="deg")
    unit = (u.hourangle, u.deg) if re.search(r"[h:]", parts[0]) or " " in text else (u.deg, u.deg)
    return SkyCoord(text, unit=unit)


# A typed position within this distance of a known fast mover's track (any epoch 1990-2030) is
# taken to mean that object, so its proper motion is applied. Catalogue coordinates of nearby stars
# and brown dwarfs are often decades old: the challenge's own WISE 0855 position is ~2' from where
# the brown dwarf is in 2026, which would put it outside a 6' view.
MATCH_RADIUS_ARCSEC = 30.0
MATCH_MIN_PM_MAS = 100.0


def _match_known(c):
    years = np.arange(-10.0, 30.25, 0.25)  # offsets from J2000
    for info in KNOWN.values():
        if np.hypot(info["pmra"], info["pmdec"]) < MATCH_MIN_PM_MAS:
            continue
        cosd = np.cos(np.radians(info["dec"]))
        track = SkyCoord(info["ra"] + info["pmra"] * years / 3.6e6 / cosd,
                         info["dec"] + info["pmdec"] * years / 3.6e6, unit="deg")
        if c.separation(track).arcsec.min() < MATCH_RADIUS_ARCSEC:
            return info
    return None


def resolve(query, pmra=None, pmdec=None):
    """Resolve `query`; explicit pmra/pmdec (mas/yr) override catalogue motion for coordinates."""
    query = query.strip()
    note = ""
    if _COORD_RE.match(query):
        c = _parse_coords(query)
        known = _match_known(c) if pmra is None and pmdec is None else None
        if known:
            info = known
            note = (f"Your coordinates match {known['name']}, a fast-moving object, so the view follows it "
                    f"to where it is in {config.VIEW_EPOCH[:4]}. {known.get('hint', '')}").strip()
        else:
            info = dict(name=c.to_string("hmsdms", precision=1), ra=c.ra.deg, dec=c.dec.deg,
                        pmra=pmra or 0.0, pmdec=pmdec or 0.0, parallax=None)
    else:
        info = _cached_sesame(query)

    kwargs = dict(ra=info["ra"] * u.deg, dec=info["dec"] * u.deg,
                  pm_ra_cosdec=info["pmra"] * u.mas / u.yr, pm_dec=info["pmdec"] * u.mas / u.yr,
                  obstime=Time("J2000"))
    if info["parallax"] and info["parallax"] > 0:
        kwargs["distance"] = Distance(parallax=info["parallax"] * u.mas)
    c2000 = SkyCoord(**kwargs)
    now = c2000.apply_space_motion(new_obstime=Time(config.VIEW_EPOCH))
    return Target(
        query=query, name=info["name"], ra=float(now.ra.deg), dec=float(now.dec.deg),
        ra_j2000=info["ra"], dec_j2000=info["dec"], pmra=info["pmra"], pmdec=info["pmdec"],
        parallax=info["parallax"], moved_arcsec=float(c2000.separation(now).arcsec), note=note,
    )
