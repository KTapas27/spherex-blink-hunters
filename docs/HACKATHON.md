# Hackathon checklist (Nov 14–15, 2026)

## Rules that matter (Project Submission Guide, read 2026-11-14)
- **Deadline: Sunday Nov 15, 11:59 pm in your Local Event's time zone.** Click "Submit for Judging"; you can resubmit until then.
- Demo: **video ≤ 30 s** (English, or subtitles) **or ≤ 7 slides**. Over the limit = not eligible for Global judging.
- Project page fields: name, high-level summary, demo link, final project link (public, no login), detailed
  description, Super Intelligence (AI) use, NASA data used, partner data/other references.
- Judged on **Impact, Creativity, Validity, Relevance, Presentation**.
- **AI ("SI") use must be acknowledged** in descriptive text/metadata for code; AI must not be used to come up with the
  idea itself. See the "AI assistance" section in README.md.
- Images on the project page: JPG/PNG/GIF ≤ 10 MB. Video/slides must be links (YouTube, Drive, GitHub).
- No images/video/audio of people under 18.
- If you host a new website, optionally request a FortiGuard web-filter classification so judges can open it.

## Where the resources are
- **Challenge Resources tab** (live since Nov 13): IRSA SPHEREx page, IRSA tutorial notebooks, WiseView, Gaia DR3,
  plus CSA NEOSSat asteroid data (optional partner data, worth citing).
  <https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=resources>
- **Space Apps Connect** (GitHub Discussions, *not* a data repo): <https://github.com/nasa/spaceapps/discussions>.
  Ask questions here; Navigators and experts answer.
  - SPHEREx thread #1847 (Navigator answer): match wavelengths before blinking, align with WCS, correct for proper
    motion, add a light curve and position-vs-time plot, call results *candidates* not discoveries, and favour
    scientific accuracy over feature count. <https://github.com/nasa/spaceapps/discussions/1847>
  - IRSA help pages cited there: <https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/cutouts.html>,
    <https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/visualization.html>
- **No pre-built dataset** for the 5 targets has been announced, so the IRSA archive is the source (we cache it).
- **Global Offers** (free, may ask for a card for verification): Google Cloud (Cloud Run for our backend, pick a
  US-east region near the SPHEREx S3 bucket), Microsoft Azure, GoDaddy domain + 1-year hosting.
  <https://www.spaceappschallenge.org/2026/global-offers/>
- Guides: Project Submission <https://www.spaceappschallenge.org/resources/project-submission-guide>,
  Judging & Awards <https://www.spaceappschallenge.org/resources/judging-awards-guide>,
  FAQs <https://www.spaceappschallenge.org/resources/participant-faqs/>

## Done (working end to end on localhost)
- [x] Name/coordinate input, presets for the 5 test targets, proper-motion correction to 2026.0
- [x] Live archive search (DR1 + QR3), visit grouping, fast S3 partial reads + cutout fallback, disk cache
- [x] Alignment, zodi subtraction, flag masking, per-visit/per-detector stacks
- [x] Blink player (speed, zoom, step, keyboard ←/→/space), detector picker D1–D6 / All
- [x] Difference mode (visit N − visit 1)
- [x] Click → spectrum (aperture photometry over every exposure, coloured by visit)
- [x] Gaia DR3 overlay at epoch 2026.0 with proper-motion arrows
- [x] Flag overlay, invert, crosshair, shareable URL hash, target info + visit table
- [x] Pre-cache script for demo targets
- [x] **Wavelength-matched blinking** (Navigator advice): 17 log-λ channels per detector; only channels seen in 2+
      visits are offered; shareable via `&ch=`
- [x] **Brightness-over-time** chart at the clicked position (per detector or per matched channel), labelled as
      candidates
- [x] **Position-over-time** chart (light-centre offset per detector and visit): separates movers from fixed stars
      and reveals blends
- [x] All 5 targets pre-built with **every** exposure (1,948 exposures, ~267 MB cache)

## Next, in priority order
1. [ ] **Check all 5 targets** in the UI after `scripts/precache.py`; tune stretch if a target looks washed out.
1b. [x] **WISE 0855 detection**: confirmed with all exposures. It's blended with a background star, but its D5/D6
       position drifts west and its spectrum rises at 4–5 µm (see BRIEFING). Demo it with the "all" exposures setting.
2. [ ] **Deploy** (Hugging Face Spaces Docker, Render or Fly, ideally a US region near AWS us-east-1):
       add a Dockerfile, copy the pre-built `cache/` for the demo targets.
3. [ ] "All frames" mode: every single exposure within one visit in time order (for asteroids).
5. [ ] Overlay the Gaia/catalogue-predicted motion on the position-over-time chart for comparison.
6. [ ] Exact flux calibration with the solid-angle pixel maps (S3 `dr1/solid_angle_pixel_map`).
7. [ ] Aladin panel: fall back to a different HiPS server or hide it when CDS is down.
8. [ ] Shift-and-add for a user-supplied motion (WiseView feature) to reveal faint movers.
9. [ ] Mobile layout polish, favicon, an About/How-to panel for the public.

## Submission (check the Space Apps site for exact requirements)
- [ ] Project page: summary, how it uses NASA data, tools, team
- [ ] 30-second video
- [ ] Public repo link (GitHub) + live demo link
- [ ] Mention: SPHEREx/IRSA, Gaia DR3, WiseView inspiration, AI assistance if required by the rules

## Demo script (2 minutes)
1. "Pluto was found by blinking two photos. SPHEREx photographs the whole sky every 6 months, in 102 colours."
2. Barnard's Star → Blink (All) → switch to **Difference, D6**: the black/white pair is the star moving 10″/yr.
3. Turn on **Gaia overlay**: the orange arrow predicts exactly that motion.
4. WISE 0855 (exposures: all) → click the centre. The **spectrum** rises at 4–5 µm, the coldest brown dwarf's
   signature. **Position over time**: D1–D4 stay put (a background star), D5/D6 slide west. Two objects in one
   pixel, told apart by colour and motion.
4b. RW Aurigae → Match wavelength on D2 → brightness over time rises while D6 fades (a young star's disk).
5. Click a field star → **spectrum** appears from ~40 exposures.
6. Copy the link: "Anyone can share or embed any patch of sky."

## 30-second video storyboard
0–5 s hook (Pluto blink) · 5–15 s Barnard's Star difference + Gaia arrow · 15–22 s WISE 0855 D1→D6 ·
22–27 s click → spectrum · 27–30 s URL + "Blink Hunters, find your own Planet X".
