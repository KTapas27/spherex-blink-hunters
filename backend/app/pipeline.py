"""End-to-end: query -> exposures -> stamps -> frames, run as background jobs."""
import concurrent.futures
import hashlib
import json
import logging
import math
import threading
import time
import traceback
from types import SimpleNamespace

import numpy as np

from . import archive, config, fetch, frames, resolve, spectrum

log = logging.getLogger(__name__)

PRESETS = [
    dict(label="Barnard's Star", query="Barnard's Star", note="fastest-moving star (10.4\"/yr)"),
    dict(label="Epsilon Indi B", query="eps Ind B", note="brown-dwarf pair, ~4.7\"/yr"),
    dict(label="WISE 0855", query="WISE J085510.83-071442.5", note="coldest brown dwarf; look in D5/D6"),
    dict(label="RW Aurigae", query="RW Aur", note="young irregular variable"),
    dict(label="R Draconis", query="R Dra", note="Mira variable, ~245-day period"),
]

_jobs = {}
_lock = threading.Lock()
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def view_key(target, fov_deg, per_group):
    raw = (f"{target.ra:.5f}|{target.dec:.5f}|{fov_deg:.4f}|{per_group}|"
           f"{','.join(config.COLLECTIONS)}|v{config.VIEW_VERSION}")
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def stamp_half_size(fov_deg):
    # Half-diagonal of the view (rotation margin) plus room for the photometry annulus.
    return int(math.ceil(fov_deg * 3600 / config.PIXEL_SCALE_ARCSEC / 2 * math.sqrt(2))) + 8


def _set(key, **kw):
    with _lock:
        _jobs.setdefault(key, {}).update(kw)


def _run(key, target, fov_deg, per_group):
    t0 = time.time()
    try:
        _set(key, status="searching", message="Searching the SPHEREx archive")
        exposures = archive.find_exposures(target.ra, target.dec)
        visits = archive.visit_summary(exposures)
        chosen = archive.pick_subset(exposures, per_group)
        half = stamp_half_size(fov_deg)
        _set(key, status="downloading", total=len(chosen), done=0, n_available=len(exposures),
             message=f"Downloading {len(chosen)} of {len(exposures)} exposures")
        stamps = fetch.get_stamps(chosen, target.ra, target.dec, half,
                                  progress=lambda d, n: _set(key, done=d, total=n))
        _set(key, status="processing", message="Aligning and combining frames")
        manifest = frames.build_frames(config.VIEW_DIR / key, target, chosen, stamps, fov_deg, visits)
        manifest.update(key=key, stamp_half=half, per_group=per_group,
                        n_available=len(exposures), elapsed_s=round(time.time() - t0, 1))
        (config.VIEW_DIR / key / "manifest.json").write_text(json.dumps(manifest, indent=1))
        _set(key, status="done", message="Ready", manifest=manifest)
    except Exception as err:
        log.error("view %s failed: %s", key, traceback.format_exc())
        _set(key, status="error", message=str(err))


def start_view(query, fov_deg=0.1, per_group=6):
    target = resolve.resolve(query)
    key = view_key(target, fov_deg, per_group)
    cached = config.VIEW_DIR / key / "manifest.json"
    if cached.exists():
        _set(key, status="done", message="Ready (cached)", manifest=json.loads(cached.read_text()))
    else:
        with _lock:
            running = _jobs.get(key, {}).get("status") not in (None, "done", "error")
        if not running:
            _set(key, status="queued", message="Queued", target=target.as_dict(), manifest=None)
            _pool.submit(_run, key, target, fov_deg, per_group)
    return key


def job(key):
    with _lock:
        if key in _jobs:
            return dict(_jobs[key])
    cached = config.VIEW_DIR / key / "manifest.json"
    if cached.exists():
        return dict(status="done", message="Ready (cached)", manifest=json.loads(cached.read_text()))
    return None


def view_spectrum(key, ra, dec):
    manifest = json.loads((config.VIEW_DIR / key / "manifest.json").read_text())
    centre = manifest["target"]
    half = manifest["stamp_half"]
    exps, stamps = [], {}
    for e in manifest["exposures"]:
        path = config.STAMP_DIR / f"{e['key']}_{centre['ra']:.5f}_{centre['dec']:.5f}_{half}.npz"
        if not path.exists():
            continue
        with np.load(path) as data:
            if data.files:
                stamps[e["key"]] = {k: data[k] for k in data.files}
                exps.append(SimpleNamespace(**e))
    return spectrum.measure(stamps, exps, ra, dec)
