# Space Apps project page: ready-to-paste text

Fields follow the 2026 Project Submission Guide. Submit before **Sun 15 Nov, 11:59 pm** (Team Owner's local
time), then click **Submit for Judging**. Check every link in a private browser window first.

---

## Project Name
Blink Hunters

## High-Level Project Summary
Blink Hunters is a free web tool that turns NASA SPHEREx's all-sky infrared images into a looping "sky video"
for any patch of sky. Type a name or coordinates and it shows that spot in every six-monthly SPHEREx visit, so
moving stars, brown dwarfs and asteroids jump between frames, and variable stars flicker. Difference and
add/subtract modes, a colour view built from SPHEREx's six detectors, and click-for-spectrum turn SPHEREx's
102 colours into something anyone can explore. It is the "blink comparator" that found Pluto, rebuilt for
SPHEREx, so volunteers can help sift a billion objects for new discoveries.

## Link to Project Demo
Video: `demo/blink_hunters_demo_29s.mp4` (29.5 s, under the 30 s limit). Upload it to YouTube (Public or Unlisted)
and paste that link; or, once it is pushed, use the GitHub link
https://github.com/KTapas27/spherex-blink-hunters/blob/main/demo/blink_hunters_demo_29s.mp4

## Link to Final Project
https://blink-hunters-8kxg.onrender.com
(Code: https://github.com/KTapas27/spherex-blink-hunters)

## Detailed Project Description

**What it does**
- Enter a name (*Barnard's Star*) or coordinates (*08h55m10.8s -07d14m42s* or *133.79 -7.24*). The tool finds
  every SPHEREx exposure of that spot, groups them into visits (SPHEREx sees the whole sky every six months),
  and plays them as a loop.
- **Blink**, **Difference** (any visit minus another, or minus the mean of the others: a mover appears as a dark/bright
  pair) and **Add / subtract** (stack visits for faint objects, or subtract sets to show what changed).
- **Per-detector views (D1-D6, 0.75-5 µm)**, all detectors stacked, or a **colour composite** (red = 3.8-5 µm,
  green = 1.6-3.8 µm, blue = 0.75-1.6 µm) in which cold brown dwarfs look red.
- **Match wavelength across visits:** SPHEREx's filters vary across each detector, so a star is seen at a slightly
  different wavelength in every exposure. The tool can blink only exposures in the same one of the 102 spectral
  channels, so a colour difference is never mistaken for motion or variability.
- **Click any object** for its **spectrum** built on the fly from every exposure, its **brightness over time** and its
  **position over time** (a mover drifts, a fixed star does not).
- **Gaia DR3 overlay** moved to the SPHEREx epoch, with arrows for fast-moving stars; **flag overlay** for
  SPHEREx's saturation and contamination flags; an **Aladin** sky view with AllWISE images for context.
- **Choose the field of view** (3'-18') and how many exposures to use.
- Every view is a **link** (e.g. `#q=Barnard's Star&det=6&mode=diff`), so views can be shared and embedded.
- **New data appears automatically:** the tool queries the live archive; a new release is one line in a config file.
- Typed coordinates of a known fast mover are followed to where it is today: the challenge's WISE 0855
  coordinates are ~3.5' from where the brown dwarf is in 2026, outside a 6' view without this.

**Results on the five test targets**
- **Barnard's Star:** in Difference mode its 10.4"/yr motion shows as a clear dark/bright pair, matching the Gaia arrow.
- **WISE 0855** (coldest known brown dwarf): visible only at 4-5 µm, using all 258 exposures. It sits one pixel from a
  background star; at 1-4 µm the light centre stays put (the star) while at 4-5 µm it drifts with WISE 0855's motion,
  and the spectrum rises sharply at 4-5 µm.
- **RW Aurigae:** brightened at 1.1-1.6 µm (≈250 → 540 mJy) while fading at 4.4-5 µm (≈2740 → 1430 mJy) across three
  visits: a colour change typical of a young star with a changing dusty disk (a candidate, not a claim).
- **Epsilon Indi B:** the brown-dwarf pair creeps between visits.
- **R Draconis:** saturated in every exposure, so the tool flags it rather than reporting false fluxes.

**How it works**
Python (FastAPI) back end; plain HTML/JavaScript front end. Exposure search with IRSA's SIA service; only the
needed pixels are read from IRSA's public copy of SPHEREx on AWS (about 4x less data than full cutouts). Each image
has zodiacal light subtracted and bad pixels masked, is reprojected onto one grid, and is combined per visit and
detector with inverse-variance weights. Spectra use aperture photometry with each pixel's own wavelength. Built with
astropy, astroquery, reproject, photutils, NumPy, Chart.js and Aladin Lite.

**Honest limits**
Fluxes use a nominal pixel size, so they are approximate (good for comparing visits, not for calibrated science).
Very bright stars saturate. Searching a brand-new position depends on IRSA's archive being online; the five test
targets are stored and work regardless.

**Why it matters**
Volunteers found most known brown dwarfs and many comets by blinking images (Backyard Worlds). Blink Hunters
gives them SPHEREx: deeper in the infrared, 102 colours, and a fresh sky every six months.

## Use of Artificial Intelligence (AI) / Super Intelligence (SI)
The project idea, scope and design decisions are the team's. Much of the code (Python back end, JavaScript front
end, scripts) and drafts of the documentation were written with an AI coding assistant (Anthropic's Claude, via
Claude Code) at the team's direction, then run and checked by the team against real SPHEREx data. No AI-generated
images, video or audio are used. This is also stated in the app ("How to use · data & credits"), in the page
metadata and in the README.

## NASA Data
- **SPHEREx** Level 2 spectral images (releases DR1 and QR3), NASA/IPAC Infrared Science Archive (IRSA),
  doi:10.26131/IRSA678; read from IRSA's public SPHEREx bucket on AWS (nasa-irsa-spherex).
- IRSA services: Simple Image Access search, cutout service, Gaia DR3 cone search.
- **AllWISE** images (NASA WISE mission, IRSA HiPS) in the context view.
- IRSA SPHEREx tutorials (caltech-ipac.github.io/irsa-tutorials/spherex) as the starting point for data handling.

## Space Agency Partner Data
- **ESA Gaia DR3** (ESA/Gaia/DPAC): star positions and proper motions for the overlay, via IRSA, ESA and VizieR.

## References / other resources
- Aladin Lite (CDS, Strasbourg); CDS Sesame name resolver.
- Python: astropy, astroquery, reproject, photutils, NumPy, SciPy, FastAPI. JavaScript: Chart.js.
- Inspiration: WiseView and Backyard Worlds: Planet 9 (backyardworlds.org).
- Navigator advice in github.com/nasa/spaceapps discussion #1847 (match wavelengths, light curves, call results
  candidates).

---

## Links for judges (open each in a private window before submitting)
- Barnard's Star moving: https://blink-hunters-8kxg.onrender.com/#q=Barnard%27s%20Star&fov=0.1&n=6&det=6&mode=diff
- WISE 0855 in colour: https://blink-hunters-8kxg.onrender.com/#q=WISE%20J085510.83-071442.5&fov=0.1&n=0&det=rgb&mode=blink
- The challenge's WISE 0855 coordinates: https://blink-hunters-8kxg.onrender.com/#q=08h55m10.831s%20-7d14m42.53s&fov=0.1&n=0&det=6&mode=blink
- RW Aurigae changing: https://blink-hunters-8kxg.onrender.com/#q=RW%20Aur&fov=0.1&n=6&det=2&mode=blink
