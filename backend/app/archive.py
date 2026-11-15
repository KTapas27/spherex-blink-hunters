"""Find SPHEREx spectral images covering a position and group them into visits."""
from __future__ import annotations  # allows `X | None` type hints on Python 3.9

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astroquery.ipac.irsa import Irsa

from . import config

log = logging.getLogger(__name__)
RETRY_WAITS_S = (2, 5, 10)


class ArchiveUnavailable(RuntimeError):
    """IRSA's image search failed every retry and there is no saved exposure list to fall back on."""


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


def _sia_cache_path(ra, dec):
    key = hashlib.sha1(f"{ra:.5f}|{dec:.5f}|{','.join(config.COLLECTIONS)}".encode()).hexdigest()[:16]
    return config.SIA_DIR / f"{key}.json"


def _search_irsa(ra, dec):
    """One SIA search, retried on failure. IRSA intermittently answers 502/503 (proxy errors)."""
    last = None
    for attempt in range(config.SIA_RETRIES):
        try:
            return Irsa.query_sia(pos=(SkyCoord(ra, dec, unit="deg"), 1 * u.arcsec),
                                  collection=config.COLLECTIONS)
        except Exception as err:  # pyvo/requests raise many types; all are worth a retry
            last = err
            log.warning("IRSA SIA attempt %d/%d failed: %s", attempt + 1, config.SIA_RETRIES, err)
            if attempt < config.SIA_RETRIES - 1:
                time.sleep(RETRY_WAITS_S[min(attempt, len(RETRY_WAITS_S) - 1)])
    raise last


def _parse(tab):
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
    return list(best.values())


def find_exposures(ra, dec):
    """All exposures covering (ra, dec), newest release wins for duplicates, sorted by time.

    The list is saved per position: a fresh copy (< SIA_CACHE_HOURS old) is reused without asking
    IRSA, and an older copy is used if IRSA is unreachable, so one archive outage can't break a
    target that has been looked at before.
    """
    path = _sia_cache_path(ra, dec)
    saved = None
    if path.exists():
        try:
            saved = json.loads(path.read_text())
        except ValueError:
            saved = None
    if saved and time.time() - saved["fetched"] < config.SIA_CACHE_HOURS * 3600:
        exposures = [Exposure(**e) for e in saved["exposures"]]
    else:
        try:
            exposures = _parse(_search_irsa(ra, dec))
        except Exception as err:
            if not saved:
                offline = exposures_from_stamps(ra, dec)
                if offline:
                    log.warning("IRSA unavailable (%s); using %d exposures already downloaded for this position",
                                err, len(offline))
                    exposures = sorted(offline, key=lambda e: e.mjd)
                    assign_visits(exposures)
                    return exposures
                raise ArchiveUnavailable(
                    "The NASA/IPAC archive (IRSA) is not answering right now "
                    f"({_short(err)}). This is on IRSA's side; please try again in a few minutes.") from err
            age_h = (time.time() - saved["fetched"]) / 3600
            log.warning("IRSA unavailable (%s); using exposure list saved %.1f h ago", err, age_h)
            exposures = [Exposure(**e) for e in saved["exposures"]]
        else:
            if exposures:  # never save an empty answer: it may be a glitch
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(dict(fetched=time.time(), ra=ra, dec=dec,
                                                collections=config.COLLECTIONS,
                                                exposures=[asdict(e) for e in exposures])))
    if not exposures:
        raise ValueError("SPHEREx has not observed this position yet (no exposures in "
                         f"{', '.join(config.COLLECTIONS)}).")
    exposures = sorted(exposures, key=lambda e: e.mjd)
    assign_visits(exposures)
    return exposures


def exposures_from_stamps(ra, dec):
    """Rebuild the exposure list from stamps already on disk for this position (no network).

    Last resort when IRSA's search is down and no exposure list was saved: every downloaded stamp
    carries its exposure id, detector and FITS header (with the observation time), which is all the
    pipeline needs, since the pixels themselves are already here. Empty (off-detector) stamps are
    skipped. Returns [] if nothing was downloaded for this position.
    """
    from astropy.io import fits

    suffix = f"_{ra:.5f}_{dec:.5f}_"
    collection_of = _collections_from_manifests()
    found = {}
    for path in config.STAMP_DIR.glob(f"*{suffix}*.npz"):
        key = path.name.split(suffix)[0]  # e.g. 2025W19_1B_0116_1_D3
        obs_id, _, det = key.rpartition("_D")
        if key in found or not det.isdigit():
            continue
        try:
            with np.load(path) as data:
                if "header" not in data.files:
                    continue
                header = fits.Header.fromstring(str(data["header"]))
            mjd = float(header["MJD-AVG"] if "MJD-AVG" in header else header["MJD-OBS"])
        except Exception as err:  # unreadable cache file: skip it
            log.warning("skipping stamp %s: %s", path.name, err)
            continue
        lo, hi = config.DETECTOR_BANDS.get(int(det), (np.nan, np.nan))
        found[key] = Exposure(obs_id=obs_id, detector=int(det),
                              collection=collection_of.get(key, config.COLLECTIONS[0]), mjd=mjd,
                              wl_min=lo, wl_max=hi, access_url="", s3_path=None)
    return list(found.values())


def _collections_from_manifests():
    """Which release each exposure came from, as recorded in built views (for the offline list)."""
    out = {}
    for manifest in config.VIEW_DIR.glob("*/manifest.json"):
        try:
            for e in json.loads(manifest.read_text()).get("exposures", []):
                out[e["key"]] = e.get("collection", config.COLLECTIONS[0])
        except (ValueError, OSError):
            continue
    return out


def _short(err):
    text = str(err).splitlines()[0] if str(err) else type(err).__name__
    return text.split(" for url:")[0][:120]


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
