# cad — FreeCAD 1.1.4 (linuxserver, browser-streamed) with the SheetMetal workbench built in (DGO-1076).
#
# Sheet metal (unfold to a flat pattern, K-factor, bends) is an add-on, not FreeCAD's core, and its unfolder
# imports networkx, which FreeCAD's own Python does not ship. Both are pinned here, so every office gets the same
# workbench without an Addon Manager click. Measured on the Dell (2026-11-01): this SheetMetal commit unfolds a
# 40 × 30 × 3 tray (t 0.024, r 0.03, K 0.44) to 45.911 × 35.911 in, 4 bends — cad-api's chase.flat() exactly.
FROM lscr.io/linuxserver/freecad:1.1.4-ls157

ARG SHEETMETAL_COMMIT=cbf6595b68ad015266923749c160c3555a72e1fd
RUN /opt/freecad/usr/bin/python -m pip install --no-cache-dir networkx==3.6.1 \
    && git clone -q https://github.com/shaise/FreeCAD_SheetMetal.git /opt/freecad/usr/Mod/SheetMetal \
    && git -C /opt/freecad/usr/Mod/SheetMetal checkout -q "${SHEETMETAL_COMMIT}" \
    && rm -rf /opt/freecad/usr/Mod/SheetMetal/.git
