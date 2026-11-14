# Blink Hunters 🔭

**NASA Space Apps 2026 · Challenge: "Planet X and SPHEREx"**

A public web tool that turns NASA SPHEREx all-sky infrared images (0.75–5 µm) into a
looping "sky video" for any patch of sky, so anyone can spot moving brown dwarfs, nearby
stars, asteroids and variable stars.

- Type a name (`Barnard's Star`) or coordinates (`08h55m10.8s -07d14m42s`, `133.79 -7.24`)
- **Blink** the images from each 6-monthly SPHEREx visit, per detector (D1–D6) or all combined
- **Difference** mode (visit N − visit 1): movers show up as a black/white pair
- **Match wavelength**: blink only exposures taken in the same one of SPHEREx's 102 channels, so a colour
  difference is never mistaken for motion or variability
- **Brightness over time** for any clicked object, per detector or per channel (flagged as *candidates*)
- **Position over time**: light-centre drift per detector. Movers drift, fixed stars don't, and blends show up
  as short and long wavelengths disagreeing (e.g. WISE 0855 next to a background star)
- **Click any star → its spectrum**, built on the fly from every exposure (up to 102 wavelengths)
- **Gaia DR3 overlay**, moved to the SPHEREx epoch, with arrows for fast-moving stars
- **Flag overlay** shows the SPHEREx contamination/saturation flags
- Every view is a shareable/embeddable URL: `/#q=R%20Dra&fov=0.1&det=6&mode=diff`
- New data releases appear automatically (live archive queries; add a release name in `backend/app/config.py`)

## Quick start

```bash
cd ~/spherex-blink-hunters
/opt/homebrew/bin/python3.13 -m venv .venv        # once (needs Python ≥ 3.11)
.venv/bin/pip install -r requirements.txt         # once
.venv/bin/uvicorn app.main:app --app-dir backend --port 8000
```

Open <http://localhost:8000>. The first view of a new target downloads ~100 small stamps
(1–3 min on home internet); after that it is cached and instant.

Pre-build the five challenge targets before a demo:

```bash
.venv/bin/python scripts/precache.py                 # all presets, 6 exposures/visit/detector
.venv/bin/python scripts/precache.py "R Dra" --per-group 15
.venv/bin/python scripts/precache.py --per-group 0   # every exposure (needed for WISE 0855)
```

Analysis notebook (reproduces every result on the five targets; a pre-run HTML copy is in `notebooks/`):

```bash
.venv/bin/pip install -r requirements-notebook.txt   # once
.venv/bin/jupyter lab notebooks/blink_hunters_walkthrough.ipynb
```

## Deploy to Google Cloud Run

The `Dockerfile` builds a self-contained image (Python 3.12, FastAPI, the UI, and anything in
`cache/`). `deploy/cloudrun.sh` builds it remotely with Cloud Build, so no local Docker is needed.
The default region is `us-east1`, next to the SPHEREx S3 bucket.

Easiest route: [Google Cloud Shell](https://shell.cloud.google.com), where `gcloud` is already installed and signed in.

```bash
git clone https://github.com/KTapas27/spherex-blink-hunters && cd spherex-blink-hunters
gcloud config set project YOUR_PROJECT_ID       # a project with billing enabled
MIN_INSTANCES=1 deploy/cloudrun.sh              # prints the public URL
deploy/warmup.sh https://YOUR-SERVICE-URL       # builds the 5 demo targets on the server
```

- **With a pre-built cache:** run `scripts/precache.py --per-group 0` first. `cache/` is then baked into the
  image, and the demo targets work instantly even after the service scales to zero.
- **Without one** (e.g. fresh clone in Cloud Shell): `warmup.sh` builds the targets on the server. They live on
  the instance's in-memory disk, so keep `MIN_INSTANCES=1` while judges may visit.
- One instance only (`--max-instances 1`): job progress is kept in memory. CPU is always on
  (`--no-cpu-throttling`), so builds keep running between status polls.
- Cost: with `MIN_INSTANCES=1`, roughly $3–4/day for 2 vCPU + 2 GiB (less with the free tier or Space Apps Google Cloud credits). Afterwards, set it back to 0
  (`gcloud run services update blink-hunters --region us-east1 --min-instances 0`) or delete the service.
- Local test: `docker build -t blink-hunters . && docker run -p 8080:8080 blink-hunters` → <http://localhost:8080>.

## How it works

```
name/coords ─► resolve.py   CDS Sesame (+ built-in values for the 5 test targets),
                            proper motion moves the position to epoch 2026.0
            ─► archive.py   IRSA SIA query (spherex_dr1 + spherex_qr3), de-duplicate,
                            group exposures into visits (gaps > 30 days)
            ─► fetch.py     read only the needed pixel rows from the public AWS S3 copy
                            (fallback: IRSA cutout service), 16 in parallel, cached as .npz
            ─► frames.py    subtract zodiacal light, mask bad flags, level background,
                            reproject onto one TAN grid, inverse-variance stack per
                            (visit, detector), render PNGs with one shared stretch
            ─► spectrum.py  aperture photometry at a clicked position in every stamp
            ─► gaia.py      Gaia DR3 cone search via IRSA, moved to epoch 2026.0
main.py      FastAPI: /api/* JSON, /views/* frames, / static UI (frontend/)
```

### API

| Endpoint | What |
|---|---|
| `GET /api/presets` | the challenge test targets |
| `GET /api/resolve?q=` | name/coords → position at epoch 2026.0 with proper motion |
| `POST /api/views` `{q, fov, per_group}` | start (or reuse) a view; returns `key` |
| `GET /api/views/{key}` | job status/progress, then the manifest (frames, visits, metadata) |
| `GET /api/views/{key}/spectrum?ra=&dec=` | spectrum points (µm, mJy) at a position |
| `GET /api/views/{key}/gaia` | Gaia DR3 sources in view pixel coordinates |

## Layout

```
backend/app/      Python backend (FastAPI)
frontend/         static UI (plain HTML/JS, Chart.js, Aladin Lite)
scripts/          precache.py
explore/          data probes run during setup (coverage, S3 speed test, logs)
tutorials/        IRSA tutorial scripts run on this machine + their outputs
docs/BRIEFING.md  everything we learned about SPHEREx data (read this first)
docs/HACKATHON.md checklist, demo script, video storyboard
docs/RESOURCES.md every challenge resource, what we tested, ideas ranked
notebooks/        walkthrough notebook reproducing every result (+ HTML export)
cache/            downloaded stamps + built views (git-ignored, safe to delete)
```

## AI assistance (Space Apps "Super Intelligence" disclosure)

The project idea and design decisions are the team's. Much of the code in `backend/`, `frontend/`,
`scripts/` and `explore/`, and the drafts of these docs, were written with an AI coding assistant
(Anthropic's Claude, via Claude Code) at the team's direction, then run and checked against real SPHEREx
data. No AI-generated images, video or audio are used in the app.

## Data & credits

SPHEREx data: NASA/JPL-Caltech, served by NASA/IPAC Infrared Science Archive (IRSA).
Gaia DR3: ESA/Gaia/DPAC (queried via IRSA). Name resolution: CDS Sesame.
Inspired by WiseView (Backyard Worlds).
