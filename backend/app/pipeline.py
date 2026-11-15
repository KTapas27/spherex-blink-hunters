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

from . import archive, config, fetch, frames, gaia, resolve, spectrum

log = logging.getLogger(__name__)

# The challenge's test targets, each with the settings that show it best (n = exposures per
# visit per detector, 0 = all; det = detector group; mode = blink/diff).
PRESETS = [
    dict(label="Barnard's Star", query="Barnard's Star", n=6, det="6", mode="diff",
         note="Fastest-moving star (10.4\"/yr): in Difference mode it shows as a dark/bright pair."),
    dict(label="Epsilon Indi B", query="eps Ind B", n=6, det="all", mode="blink",
         note="Brown-dwarf pair, 4.7\"/yr: blink to see it creep between visits."),
    dict(label="WISE 0855", query="WISE J085510.83-071442.5", n=0, det="rgb", mode="blink",
         note="Coldest known brown dwarf: only visible at 4-5 µm, so it looks red in the colour view. "
              "Uses every exposure."),
    dict(label="RW Aurigae", query="RW Aur", n=6, det="2", mode="blink",
         note="Young variable star: brighter at 1-1.6 µm (D2) while it fades at 4-5 µm."),
    dict(label="R Draconis", query="R Dra", n=6, det="all", mode="blink",
         note="Mira variable (~245-day period). Saturated, so judge its changes by eye."),
]

_jobs = {}
_lock = threading.Lock()
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_spec_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="spectrum")


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
        gaia.prefetch(config.VIEW_DIR / key, manifest)  # so the Gaia overlay is ready when asked for
        prefetch_spectrum(key, manifest)  # the target's own spectrum is the first thing people click
    except Exception as err:
        log.error("view %s failed: %s", key, traceback.format_exc())
        _set(key, status="error", message=str(err))


def start_view(query, fov_deg=0.1, per_group=6):
    target = resolve.resolve(query)
    key = view_key(target, fov_deg, per_group)
    cached = config.VIEW_DIR / key / "manifest.json"
    if cached.exists():
        manifest = json.loads(cached.read_text())
        _set(key, status="done", message="Ready (cached)", manifest=manifest)
        gaia.prefetch(config.VIEW_DIR / key, manifest)  # no-op if gaia.json is already cached
        prefetch_spectrum(key, manifest)  # no-op if already measured
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


# ---------- spectra ----------
# A spectrum reads every stamp of the view and builds each one's WCS, which takes minutes on a
# small cloud CPU. So: (1) the prepared stamps of the most recent view stay in memory, (2) results
# are saved per view pixel in spectra.json, and (3) the target's own pixel is measured in the
# background as soon as a view is opened, before anyone clicks it.
_prepared = {"key": None, "items": None}
_prepared_lock = threading.Lock()
_spec_locks = {}


def _prepared_for(key, manifest):
    with _prepared_lock:
        if _prepared["key"] == key:
            return _prepared["items"]
        centre, half = manifest["target"], manifest["stamp_half"]
        exps, stamps = [], {}
        for e in manifest["exposures"]:
            path = config.STAMP_DIR / f"{e['key']}_{centre['ra']:.5f}_{centre['dec']:.5f}_{half}.npz"
            if not path.exists():
                continue
            with np.load(path) as data:
                if data.files:
                    stamps[e["key"]] = {k: data[k] for k in data.files}
                    exps.append(SimpleNamespace(**e))
        items = spectrum.prepare(stamps, exps)
        _prepared.update(key=key, items=items)
        return items


def _snap(manifest, ra, dec):
    """The view pixel containing (ra, dec), and that pixel's centre on the sky."""
    from astropy.coordinates import SkyCoord
    t = manifest["target"]
    w, _ = frames.grid_wcs(t["ra"], t["dec"], manifest["fov_deg"])
    x, y = (int(round(float(v))) for v in w.world_to_pixel(SkyCoord(ra, dec, unit="deg")))
    c = w.pixel_to_world(x, y)
    return f"{x},{y}", float(c.ra.deg), float(c.dec.deg)


def view_spectrum(key, ra, dec):
    """(points, n_flagged) at the view pixel containing (ra, dec); cached per pixel."""
    view_dir = config.VIEW_DIR / key
    manifest = json.loads((view_dir / "manifest.json").read_text())
    pix, pra, pdec = _snap(manifest, ra, dec)
    cache = view_dir / "spectra.json"
    with _lock:
        lock = _spec_locks.setdefault((key, pix), threading.Lock())
    with lock:  # a click on a pixel that is being prefetched waits for that result
        saved = json.loads(cache.read_text()) if cache.exists() else {}
        if pix in saved:
            return saved[pix]["points"], saved[pix]["n_flagged"]
        points, n_flagged = spectrum.measure_prepared(_prepared_for(key, manifest), pra, pdec)
        with _lock:
            saved = json.loads(cache.read_text()) if cache.exists() else {}
            saved[pix] = dict(points=points, n_flagged=n_flagged)
            cache.write_text(json.dumps(saved))
        return points, n_flagged


def prefetch_spectrum(key, manifest):
    """Measure the target's own pixel in the background (errors are only logged)."""
    def run():
        try:
            view_spectrum(key, manifest["target"]["ra"], manifest["target"]["dec"])
        except Exception as err:
            log.warning("spectrum prefetch for %s failed: %s", key, err)
    _spec_pool.submit(run)
