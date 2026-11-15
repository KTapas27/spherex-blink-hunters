"""FastAPI app: JSON API under /api, rendered frames under /views, the web UI at /."""
import logging

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import astrometry, combine, config, gaia, pipeline, resolve

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Blink Hunters: SPHEREx time-lapse viewer")
config.VIEW_DIR.mkdir(parents=True, exist_ok=True)


class ViewRequest(BaseModel):
    q: str = Field(..., description="Object name or 'RA Dec' (degrees or sexagesimal)")
    fov: float = Field(0.1, ge=0.02, le=0.5, description="Field of view in degrees")
    per_group: int = Field(6, ge=0, le=200, description="Max exposures per visit+detector (0 = all)")


@app.get("/api/health")
def health():
    """Liveness check for the hosting platform."""
    return {"ok": True, "cached_views": sum(1 for _ in config.VIEW_DIR.glob("*/manifest.json"))}


@app.get("/api/presets")
def presets():
    return pipeline.PRESETS


@app.get("/api/resolve")
def api_resolve(q: str):
    try:
        return resolve.resolve(q).as_dict()
    except Exception as err:
        raise HTTPException(404, f"Could not resolve '{q}': {err}")


@app.post("/api/views")
def create_view(req: ViewRequest):
    try:
        key = pipeline.start_view(req.q, req.fov, req.per_group)
        note = resolve.resolve(req.q).note  # cached: no second lookup
    except LookupError as err:
        raise HTTPException(404, str(err))
    return {"key": key, "note": note, **(pipeline.job(key) or {})}


@app.get("/api/views/{key}")
def get_view(key: str):
    state = pipeline.job(key)
    if state is None:
        raise HTTPException(404, "Unknown view")
    return {"key": key, **state}


@app.get("/api/views/{key}/spectrum")
def get_spectrum(key: str, ra: float = Query(...), dec: float = Query(...)):
    state = pipeline.job(key)
    if not state or state.get("status") != "done":
        raise HTTPException(409, "View is not ready")
    points, n_skipped = pipeline.view_spectrum(key, ra, dec)
    return {"ra": ra, "dec": dec, "points": points, "n_flagged": n_skipped}


@app.get("/api/views/{key}/positions")
def get_positions(key: str, ra: float = Query(...), dec: float = Query(...)):
    state = pipeline.job(key)
    if not state or state.get("status") != "done":
        raise HTTPException(409, "View is not ready")
    return {"ra": ra, "dec": dec, "points": astrometry.positions(config.VIEW_DIR / key, ra, dec)}


@app.get("/api/views/{key}/gaia")
def get_gaia(key: str):
    state = pipeline.job(key)
    if not state or state.get("status") != "done":
        raise HTTPException(409, "View is not ready")
    try:
        return {"epoch": config.VIEW_EPOCH,
                "sources": gaia.sources_for_view(config.VIEW_DIR / key, state["manifest"])}
    except Exception as err:
        raise HTTPException(502, f"Gaia query failed: {err}")


@app.get("/api/views/{key}/combine")
def get_combine(key: str, group: str = Query("all"), plus: str = Query(..., description="visits to add, e.g. 0,2"),
                minus: str = Query("", description="visits to subtract, e.g. 1")):
    """Add and/or subtract any visits (numbered from 0) of one frame group; returns the PNG name."""
    state = pipeline.job(key)
    if not state or state.get("status") != "done":
        raise HTTPException(409, "View is not ready")
    try:
        to_list = lambda s: [int(x) for x in s.split(",") if x.strip() != ""]
        return combine.combine(config.VIEW_DIR / key, state["manifest"], group, to_list(plus), to_list(minus))
    except (combine.CombineError, ValueError) as err:
        raise HTTPException(400, str(err))


app.mount("/views", StaticFiles(directory=config.VIEW_DIR), name="views")
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="ui")
