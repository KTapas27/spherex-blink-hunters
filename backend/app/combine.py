"""Add and subtract any visits of a view, on request.

`combine(view_dir, manifest, group, plus=[0, 2], minus=[1])` renders
    (weighted mean of visits 1 and 3) - (visit 2)
for one frame group ("all", "rgb", a detector "5", or a channel "5:3"). With no `minus` visits
it is a deep stack: all chosen visits added together for the faintest objects. Visits are
numbered from 0 here; the UI shows them from 1.

Each visit's stack is weighted by its inverse variance, so a visit with more (or cleaner)
exposures counts for more, as in the per-visit stacks themselves. Results are cached as PNGs
in the view folder, so asking twice costs nothing.
"""
import numpy as np

from . import frames


class CombineError(ValueError):
    """The request can't be rendered (unknown group, bad visit numbers)."""


def _weighted_mean(stacks, weights, visits, key):
    num = den = None
    for v in visits:
        s = stacks[key(v)].astype(np.float64)
        w = weights[key(v)].astype(np.float64) if weights is not None else np.ones_like(s)
        ok = np.isfinite(s) & np.isfinite(w) & (w > 0)
        n_part, d_part = np.where(ok, s * w, 0.0), np.where(ok, w, 0.0)
        num = n_part if num is None else num + n_part
        den = d_part if den is None else den + d_part
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _load(view_dir, tag):
    with np.load(view_dir / f"stack_{tag}.npz") as data:
        stacks = {k: data[k] for k in data.files}
    weight_path = view_dir / f"weight_{tag}.npz"
    weights = None
    if weight_path.exists():
        with np.load(weight_path) as data:
            weights = {k: data[k] for k in data.files}
    return stacks, weights


def label(plus, minus):
    def side(vs):
        return ("Visit " if len(vs) == 1 else "Visits ") + "+".join(str(v + 1) for v in vs)
    if not minus:
        return f"{side(plus)} added" if len(plus) > 1 else side(plus)
    return f"{side(plus)} − {side(minus)}"


def combine(view_dir, manifest, group, plus, minus=()):
    groups = manifest.get("groups") or {}
    info = groups.get(group)
    if info is None:
        raise CombineError(f"No frames for group '{group}' in this view (rebuild older views to add/subtract).")
    plus, minus = sorted(set(plus)), sorted(set(minus))
    available = set(info["visits"])
    if not plus:
        raise CombineError("Pick at least one visit to add.")
    if set(plus) & set(minus):
        raise CombineError("A visit can't be both added and subtracted.")
    missing = (set(plus) | set(minus)) - available
    if missing:
        raise CombineError(f"Visit(s) {', '.join(str(v + 1) for v in sorted(missing))} have no data in this group.")

    tag = info["tag"]
    name = f"combo_{tag}_p{''.join(map(str, plus))}_m{''.join(map(str, minus))}.png"
    path = view_dir / name
    if not path.exists():
        stacks, weights = _load(view_dir, tag)
        if info["kind"] == "rgb":
            bands, limits = {}, {}
            for band, lim in info["limits"].items():
                if not all(f"v{v}_{band}" in stacks for v in plus + minus):
                    continue  # this colour wasn't observed in every chosen visit: leave it out
                key = lambda v, b=band: f"v{v}_{b}"
                img = _weighted_mean(stacks, weights, plus, key)
                if minus:
                    img = img - _weighted_mean(stacks, weights, minus, key)
                bands[band] = img
                limits[band] = lim["dmax"] if minus else (lim["vmin"], lim["vmax"])
            if not bands:
                raise CombineError("No colour was observed in all the chosen visits.")
            frames.to_rgb_png(bands, path, limits, diverging=bool(minus))
        else:
            key = lambda v: f"v{v}"
            img = _weighted_mean(stacks, weights, plus, key)
            if minus:
                img = img - _weighted_mean(stacks, weights, minus, key)
                frames.to_png(img, path, 0, info["dmax"] or 1.0, diverging=True)
            else:
                frames.to_png(img, path, info["vmin"], info["vmax"])

    visits = {v["visit"]: v for v in manifest["visits"]}
    used = plus + minus
    return dict(
        group=group, file=name, plus=plus, minus=minus, label=label(plus, minus),
        kind="difference" if minus else ("stack" if len(plus) > 1 else "single"),
        start=min(visits[v]["start"] for v in used), end=max(visits[v]["end"] for v in used),
    )
