# cad — FreeCAD in the office

What it is for: a person designs, checks and draws for production — FreeCAD 1.1 in the browser (tile
«מודלים תלת־ממד», FreeCAD in English). The parametric models a job is priced from are the **cad-api** app (its own AGENT.md);
this app is where a person opens what it builds.

- Sheet metal comes from the SheetMetal workbench, built into the image (freecad/Dockerfile, a pinned
  commit + networkx). Headless: `/opt/freecad/usr/bin/freecadcmd` inside the container —
  `SheetMetalNewUnfolder.getUnfold` unfolds a part to its flat blank (a 40×30×3 tray: 45.911 × 35.911,
  the same as cad-api's chase cover, measured 2026-11-01).
- The models cad-api writes land in `/config/projects/out` here (the shared `cad_projects` volume),
  owned by FreeCAD's user: File → Open.

Traps:
- FreeCAD streams a desktop: one person per session, and it is the heavy one (2 CPU / 3 GB). The herd
  runs it on the HP or the Dell, not on the Mac; an office that only prices caps runs cad-api alone.
- A FreeCAD stopped mid-session leaves recovery files in `/config/.cache/FreeCAD/v1-1/Cache/`; the next
  start opens a modal «Document Recovery» over everything until it is answered.
- The X display inside the container is `:0`, and a second FreeCAD starts only through `/opt/freecad/AppRun`.
