#!/bin/sh
# frame-shim.sh — lets the REAL Obsidian boot inside the office console's frame.
#
# WHY. The console shows this app in a frame on its own host (app.json `module.external`), so the
# page's parent is the console — another origin. Obsidian's window setup walks up `window.parent`
# to the topmost window and reads `.require` from it (it is looking for Electron's main window):
#     for (var t = e; t !== t.parent && null !== t.parent;) t = t.parent;   var n = t.require;
# Reading a property of a cross-origin window throws, so the boot stopped right there. Measured
# 2026-10-07 in the owner's browser: "SecurityError: Failed to read a named property 'require'
# from 'Window'" and an empty grey frame, while the very same URL in a tab of its own worked.
#
# WHAT. One line at the top of the page Ignis serves: inside a frame, this window is its own
# parent (`window.parent` is [Replaceable] in every browser). Obsidian then finds the shimmed
# `require` on its own window, exactly as it does in a tab. Nothing of Obsidian's is touched —
# the line goes into Ignis's page TEMPLATE, in the container's own filesystem, before the server
# starts — and in a tab of its own the line does nothing at all.
#
# Idempotent (a marker). A template with no <head> to anchor on is left alone and said so: an image
# update must degrade to "Obsidian does not boot inside the frame", never to a container that
# does not start.
T=/app/apps/ignis-server/server/assets/index.html
MARK=office-frame-shim
if [ -f "$T" ] && ! grep -q "$MARK" "$T"; then
  if grep -q '<head>' "$T"; then
    sed -i "s#<head>#<head><script>/* $MARK */ try { if (window.parent !== window) window.parent = window; } catch (e) {}</script>#" "$T" \
      && echo "[office] frame shim added to the page template"
  else
    echo "[office] WARNING: no <head> in $T - frame shim NOT added; Obsidian will not boot inside the console's frame" >&2
  fi
fi
exec "$@"
