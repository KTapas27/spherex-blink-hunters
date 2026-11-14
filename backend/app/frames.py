"""Align stamps onto one sky grid, combine them per visit, render blink/difference frames.

Besides the per-detector and per-channel groups, a colour composite group ("rgb") maps the six
detectors onto three colours: blue = D1+D2 (0.75-1.6 um), green = D3+D4 (1.6-3.8 um),
red = D5+D6 (3.8-5.0 um). Hot stars come out blue-white, cool stars orange, and very cold brown
dwarfs (which glow mostly at 4-5 um) stand out red.
"""
import json

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS
from PIL import Image
from reproject import reproject_interp
from scipy.ndimage import distance_transform_edt

from . import config

NAN_RGB = (40, 110, 255)  # flag-overlay colour for pixels with no good data (flagged / off detector)


def grid_wcs(ra, dec, fov_deg, scale_arcsec=config.PIXEL_SCALE_ARCSEC):
    n = int(round(fov_deg * 3600 / scale_arcsec)) | 1  # odd, so the target sits on a pixel centre
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    w.wcs.cdelt = [-scale_arcsec / 3600, scale_arcsec / 3600]
    return w, (n, n)


def clean(stamp):
    """Zodi-subtracted, flag-masked, background-levelled image and variance."""
    img = stamp["image"].astype(np.float64) - stamp["zodi"]
    var = stamp["variance"].astype(np.float64)
    bad = ((stamp["flags"].astype(np.int64) & config.BAD_FLAG_MASK) != 0) | ~np.isfinite(img) | ~(var > 0)
    img[bad] = np.nan
    var[bad] = np.nan
    if np.isfinite(img).sum() > 20:
        _, median, _ = sigma_clipped_stats(img, sigma=3)
        img -= median
    return img, var


def stamp_wcs(stamp):
    return WCS(fits.Header.fromstring(str(stamp["header"])))


def align(stamp, out_wcs, shape):
    img, var = clean(stamp)
    wcs = stamp_wcs(stamp)
    img_r, _ = reproject_interp((img, wcs), out_wcs, shape_out=shape)
    var_r, _ = reproject_interp((var, wcs), out_wcs, shape_out=shape)
    return img_r, var_r


def coadd(images, variances, return_weight=False):
    """Inverse-variance weighted mean, NaN-aware (and the summed weight, if asked)."""
    num = np.zeros_like(images[0])
    den = np.zeros_like(images[0])
    for img, var in zip(images, variances):
        ok = np.isfinite(img) & np.isfinite(var) & (var > 0)
        w = np.where(ok, 1.0 / np.where(ok, var, 1.0), 0.0)
        num += np.where(ok, img, 0.0) * w
        den += w
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(den > 0, num / den, np.nan)
    return (mean, den) if return_weight else mean


# Colour composite: which detectors feed which colour, and the order colours are stored in.
RGB_BANDS = {"r": (5, 6), "g": (3, 4), "b": (1, 2)}
BAND_OF_DETECTOR = {d: band for band, dets in RGB_BANDS.items() for d in dets}
BAND_ORDER = ("r", "g", "b")


def _stretch(x, vmin, vmax, asinh_a=0.1):
    x = np.clip((x - vmin) / (vmax - vmin), 0, 1)
    return np.arcsinh(x / asinh_a) / np.arcsinh(1 / asinh_a)


def to_rgb_png(bands, path, limits, diverging=False):
    """Save a colour PNG from three images (r, g, b) plus a flag mask beside it.

    `limits[band]` is (vmin, vmax) for a normal image, or dmax for a difference (grey = no
    change; a tint shows which colours brightened or faded). A band with no data stays dark
    (or grey, for a difference), so a visit missing a detector still renders.
    """
    shape = next(iter(bands.values())).shape
    bad = np.ones(shape, dtype=bool)
    planes = []
    for band in BAND_ORDER:
        data = bands.get(band)
        if data is None or not np.isfinite(data).any():
            planes.append(np.full(shape, 0.5 if diverging else 0.0))
            continue
        bad &= ~np.isfinite(data)
        filled = fill_nans(data)
        if diverging:
            dmax = limits[band] or 1.0
            planes.append(0.5 + 0.5 * np.clip(filled / dmax, -1, 1))
        else:
            planes.append(_stretch(filled, *limits[band]))
    rgb = np.nan_to_num(np.stack(planes, axis=-1) * 255, nan=0).astype(np.uint8)
    Image.fromarray(np.flipud(rgb), mode="RGB").save(path)
    rgba = np.zeros(shape + (4,), dtype=np.uint8)
    rgba[bad] = (*NAN_RGB, 200)
    Image.fromarray(np.flipud(rgba), mode="RGBA").save(path.with_name("mask_" + path.name))


def _limits(stacks):
    """Display range shared by all visits of a group: (vmin, vmax) and a difference scale."""
    finite = np.concatenate([s[np.isfinite(s)] for s in stacks.values()])
    if finite.size == 0:
        return None
    vmin, vmax = (float(v) for v in np.percentile(finite, [5, 99.7]))
    if vmax <= vmin:
        vmax = vmin + 1e-6
    # Typical size of a visit-to-visit change: the spread of each visit about the all-visit mean.
    mean = np.nanmean(np.stack(list(stacks.values())), axis=0) if len(stacks) > 1 else None
    if mean is not None:
        dev = np.concatenate([(s - mean)[np.isfinite(s - mean)] for s in stacks.values()])
        dmax = float(np.percentile(np.abs(dev), 99.5)) * 2 if dev.size else 0.0
    else:
        dmax = 0.0
    return vmin, vmax, dmax or (vmax - vmin) * 0.1


def fill_nans(data):
    """Fill flagged holes (e.g. saturated star cores) with the nearest good pixel."""
    bad = ~np.isfinite(data)
    if not bad.any() or bad.all():
        return data
    idx = distance_transform_edt(bad, return_distances=False, return_indices=True)
    return data[tuple(idx)]


def to_png(data, path, vmin, vmax, asinh_a=0.1, diverging=False):
    """Save a greyscale PNG with holes filled, plus a transparent flag-mask PNG beside it."""
    bad = ~np.isfinite(data)
    filled = fill_nans(data)
    if diverging:
        scaled = 0.5 + 0.5 * np.clip(filled / vmax, -1, 1)
    else:
        x = np.clip((filled - vmin) / (vmax - vmin), 0, 1)
        scaled = np.arcsinh(x / asinh_a) / np.arcsinh(1 / asinh_a)
    gray = np.nan_to_num(scaled * 255, nan=0).astype(np.uint8)
    Image.fromarray(np.flipud(gray), mode="L").save(path)  # FITS row 0 is the bottom
    rgba = np.zeros(data.shape + (4,), dtype=np.uint8)
    rgba[bad] = (*NAN_RGB, 200)
    Image.fromarray(np.flipud(rgba), mode="RGBA").save(path.with_name("mask_" + path.name))


def channel_of(detector, wl_um):
    """Index (0..CHANNELS_PER_DETECTOR-1) of the log-wavelength channel `wl_um` falls in."""
    lo, hi = config.DETECTOR_BANDS[detector]
    frac = np.log(wl_um / lo) / np.log(hi / lo)
    return int(np.clip(np.floor(frac * config.CHANNELS_PER_DETECTOR), 0, config.CHANNELS_PER_DETECTOR - 1))


def channel_centre(detector, channel):
    lo, hi = config.DETECTOR_BANDS[detector]
    return float(lo * (hi / lo) ** ((channel + 0.5) / config.CHANNELS_PER_DETECTOR))


def _group_order(gid):
    """'all' first, then detectors 1-6, each followed by its wavelength channels."""
    if gid == "all":
        return (0, 0, -1)
    if gid == "rgb":
        return (0, 1, -1)
    det, _, ch = gid.partition(":")
    return (1, int(det), int(ch) if ch else -1)


def build_frames(view_dir, target, exposures, stamps, fov_deg, visits):
    """Write PNG frames + manifest.json into view_dir and return the manifest dict.

    Frames are made for three kinds of group: "all" detectors, each detector ("3"), and each
    wavelength channel of a detector ("3:7"). Channel groups are only kept when at least two
    visits observed the target in that channel, since that's what makes a fair blink comparison.
    """
    out_wcs, shape = grid_wcs(target.ra, target.dec, fov_deg)
    by_group = {}
    by_band = {}  # (band "r"/"g"/"b", visit) -> aligned images, for the colour composite
    for exp in exposures:
        stamp = stamps.get(exp.key)
        if stamp is None:
            continue
        img, var = align(stamp, out_wcs, shape)
        if not np.isfinite(img).any():
            continue
        wl = float(stamp["wave"][stamp["wave"].shape[0] // 2, stamp["wave"].shape[1] // 2])
        ch = channel_of(exp.detector, wl)
        for gid in ("all", str(exp.detector), f"{exp.detector}:{ch}"):
            g = by_group.setdefault((gid, exp.visit), dict(imgs=[], vars=[], wls=[], n=0))
            g["imgs"].append(img)
            g["vars"].append(var)
            g["wls"].append(wl)
            g["n"] += 1
        band = by_band.setdefault((BAND_OF_DETECTOR[exp.detector], exp.visit), dict(imgs=[], vars=[], wls=[]))
        band["imgs"].append(img)
        band["vars"].append(var)
        band["wls"].append(wl)

    view_dir.mkdir(parents=True, exist_ok=True)
    frames, diffs, channels = [], [], []
    group_info = {}  # per group: file tag, visits, display range (used by combine.py)
    visit_info = {v["visit"]: v for v in visits}
    for gid in sorted({gid for gid, _ in by_group}, key=_group_order):
        groups = sorted((v, g) for (d, v), g in by_group.items() if d == gid)
        det_s, _, ch_s = gid.partition(":")
        det = "all" if gid == "all" else int(det_s)
        channel = int(ch_s) if ch_s else None
        if channel is not None:
            if len(groups) < 2:
                continue
            channels.append(dict(group=gid, detector=det, channel=channel,
                                 wl_center=round(channel_centre(det, channel), 3),
                                 visits=[v for v, _ in groups]))
        combined = {v: coadd(g["imgs"], g["vars"], return_weight=True) for v, g in groups}
        stacks = {v: c[0] for v, c in combined.items()}
        lim = _limits(stacks)
        if lim is None:
            continue
        vmin, vmax, dscale = lim
        tag = f"D{det}" + (f"c{channel}" if channel is not None else "")
        group_info[gid] = dict(tag=tag, kind="mono", visits=[v for v, _ in groups],
                               vmin=vmin, vmax=vmax, dmax=dscale)
        for v, g in groups:
            name = f"{tag}_v{v}.png"
            to_png(stacks[v], view_dir / name, vmin, vmax)
            frames.append(dict(
                group=gid, detector=det, channel=channel, visit=v, file=name, n_exposures=g["n"],
                wl_min=round(min(g["wls"]), 3), wl_max=round(max(g["wls"]), 3),
                start=visit_info[v]["start"], end=visit_info[v]["end"],
                good_fraction=round(float(np.isfinite(stacks[v]).mean()), 3),
            ))
        first_v = groups[0][0]
        deltas = {v: stacks[v] - stacks[first_v] for v, _ in groups[1:]}
        if deltas:
            dfin = np.concatenate([d[np.isfinite(d)] for d in deltas.values()])
            dmax = np.percentile(np.abs(dfin), 99.5) if dfin.size else 1.0
            for v, d in deltas.items():
                name = f"diff_{tag}_v{v}.png"
                to_png(d, view_dir / name, 0, dmax or 1.0, diverging=True)
                diffs.append(dict(group=gid, detector=det, channel=channel, visit=v, ref_visit=first_v,
                                  file=name, start=visit_info[v]["start"], end=visit_info[v]["end"]))
        np.savez_compressed(view_dir / f"stack_{tag}.npz",
                            **{f"v{v}": s.astype(np.float32) for v, s in stacks.items()})
        # Summed inverse-variance weights, so visits can be added together properly later.
        np.savez_compressed(view_dir / f"weight_{tag}.npz",
                            **{f"v{v}": c[1].astype(np.float32) for v, c in combined.items()})

    rgb = _build_rgb(view_dir, by_band, visit_info)
    if rgb:
        frames[:0] = rgb["frames"]
        group_info["rgb"] = rgb["info"]

    manifest = dict(
        target=target.as_dict(), fov_deg=fov_deg, shape=list(shape),
        pixel_scale_arcsec=config.PIXEL_SCALE_ARCSEC, visits=visits,
        frames=frames, diffs=diffs, channels=channels, groups=group_info,
        rgb_bands={b: list(d) for b, d in RGB_BANDS.items()},
        n_exposures_used=sum(1 for e in exposures if e.key in stamps),
        exposures=[dict(key=e.key, mjd=e.mjd, visit=e.visit, detector=e.detector,
                        collection=e.collection) for e in exposures if e.key in stamps],
        collections=sorted({e.collection for e in exposures}),
    )
    (view_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def _build_rgb(view_dir, by_band, visit_info):
    """Colour composite per visit: red = D5+D6, green = D3+D4, blue = D1+D2.

    Each colour has its own display range, shared across visits, so visits compare fairly and
    a change of colour between visits is real. Returns frames + group info, or None.
    """
    visits = sorted({v for _, v in by_band})
    stacks, weights, limits, wls = {}, {}, {}, {}
    for band in BAND_ORDER:
        per_visit = {}
        for v in visits:
            g = by_band.get((band, v))
            if g:
                mean, w = coadd(g["imgs"], g["vars"], return_weight=True)
                per_visit[v] = mean
                weights[(band, v)] = w
                wls.setdefault(v, []).extend(g["wls"])
        if not per_visit:
            continue
        lim = _limits(per_visit)
        if lim is None:
            continue
        limits[band] = lim
        for v, mean in per_visit.items():
            stacks[(band, v)] = mean
    if len(limits) < 2:  # a colour picture needs at least two colours
        return None
    frames = []
    for v in visits:
        bands = {b: stacks.get((b, v)) for b in BAND_ORDER}
        if sum(x is not None for x in bands.values()) < 2:
            continue
        name = f"RGB_v{v}.png"
        to_rgb_png(bands, view_dir / name, {b: limits[b][:2] for b in limits})
        present = [b for b in BAND_ORDER if bands[b] is not None]
        frames.append(dict(
            group="rgb", detector="rgb", channel=None, visit=v, file=name,
            n_exposures=sum(len(by_band[(b, v)]["imgs"]) for b in present),
            wl_min=round(min(wls[v]), 3), wl_max=round(max(wls[v]), 3),
            start=visit_info[v]["start"], end=visit_info[v]["end"],
            bands=present,
        ))
    if not frames:
        return None
    np.savez_compressed(view_dir / "stack_RGB.npz",
                        **{f"v{v}_{b}": s.astype(np.float32) for (b, v), s in stacks.items()})
    np.savez_compressed(view_dir / "weight_RGB.npz",
                        **{f"v{v}_{b}": w.astype(np.float32) for (b, v), w in weights.items()})
    info = dict(tag="RGB", kind="rgb", visits=[f["visit"] for f in frames],
                limits={b: dict(vmin=l[0], vmax=l[1], dmax=l[2]) for b, l in limits.items()})
    return dict(frames=frames, info=info)
