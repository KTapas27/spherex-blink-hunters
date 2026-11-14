"""Find SPHEREx spectral images covering a position and group them into visits."""
import json
from dataclasses import dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astroquery.ipac.irsa import Irsa

from . import config


@dataclass
class Exposure:
    obs_id: str
    detector: int
    collection: str
    mjd: float
    wl_min: float  # microns, whole detector
    wl_max: float
    access_url: str
    s3_path: str | None
    visit: int = -1

    @property
    def key(self):
        return f"{self.obs_id}_D{self.detector}"


def find_exposures(ra, dec):
    """All exposures covering (ra, dec), newest release wins for duplicates, sorted by time."""
    tab = Irsa.query_sia(pos=(SkyCoord(ra, dec, unit="deg"), 1 * u.arcsec),
                         collection=config.COLLECTIONS)
    rank = {c: i for i, c in enumerate(config.COLLECTIONS)}
    best = {}
    for row in tab:
        det = int(str(row["energy_bandpassname"]).split("-D")[-1])
        s3 = None
        if row["cloud_access"]:
            aws = json.loads(row["cloud_access"]).get("aws", {})
            if aws.get("bucket_name") and aws.get("key"):
                s3 = f"s3://{aws['bucket_name']}/{aws['key']}"
        exp = Exposure(
            obs_id=str(row["obs_id"]), detector=det, collection=str(row["obs_collection"]),
            mjd=float(row["t_min"]), wl_min=float(row["em_min"]) * 1e6,
            wl_max=float(row["em_max"]) * 1e6, access_url=str(row["access_url"]), s3_path=s3,
        )
        old = best.get(exp.key)
        if old is None or rank.get(exp.collection, 99) < rank.get(old.collection, 99):
            best[exp.key] = exp
    exposures = sorted(best.values(), key=lambda e: e.mjd)
    assign_visits(exposures)
    return exposures


def assign_visits(exposures):
    visit, last = 0, None
    for exp in exposures:
        if last is not None and exp.mjd - last > config.VISIT_GAP_DAYS:
            visit += 1
        exp.visit = visit
        last = exp.mjd


def visit_summary(exposures):
    out = []
    for v in sorted({e.visit for e in exposures}):
        mjds = np.array([e.mjd for e in exposures if e.visit == v])
        out.append(dict(
            visit=v,
            start=Time(mjds.min(), format="mjd").iso[:10],
            end=Time(mjds.max(), format="mjd").iso[:10],
            mid_mjd=float(np.median(mjds)),
            n=int(len(mjds)),
        ))
    return out


def pick_subset(exposures, per_group):
    """Keep at most `per_group` exposures per (visit, detector), spread evenly in time."""
    if not per_group:
        return list(exposures)
    groups = {}
    for e in exposures:
        groups.setdefault((e.visit, e.detector), []).append(e)
    chosen = []
    for items in groups.values():
        if len(items) <= per_group:
            chosen.extend(items)
        else:
            idx = np.linspace(0, len(items) - 1, per_group).round().astype(int)
            chosen.extend(items[i] for i in sorted(set(idx)))
    return sorted(chosen, key=lambda e: e.mjd)
