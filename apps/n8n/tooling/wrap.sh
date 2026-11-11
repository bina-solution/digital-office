# wrap.sh — sourced by apps/n8n/hooks/{push,push-app,pull,pull-app}. Not run on its own.
#
#   wrap_run <render|compile> <src dir> <out dir>
#
# tooling/wrap.mjs, run where node is (DGO-1746). The blueprints are TypeScript, so every push and pull runs
# wrap.mjs. On a host that has node it runs here, as it always did. On one that has none — a server office
# (Exampleu) and app-management, whose image has no node (DGO-994); this Mac's host has none either — it runs
# inside the office's own n8n container, which runs node anyway. Only `push` had that second path
# (compile_in_engine); push-app, pull and pull-app called the host's node and died on a server office:
# «no `node` on this host, and blueprints are TypeScript» (measured on Exampleu, 2026-11-10).
#
# The engine path carries the toolchain's own files in by tar (never node_modules) and the sources, runs the
# verb in the box, and brings the output back — no path has to mean the same thing on both sides, and nothing
# lands as another user. BBOX_WRAP_CACHE=1 keeps the toolchain's node_modules in the container's home, keyed by
# the lockfile (wrap.mjs toolHome): installed once per lockfile, never per run inside production n8n (the second
# reader). `render` writes only <id>.workflow.ts files and reads none from its output, so an empty output box
# gives the same files the host run writes.
#
# Needs from the hook: N8N_DIR, WRAP, N8N_CONTAINER, and lib.sh's bbox_node.

wrap_in_engine() {
  local verb="$1" src="$2" out="$3" box="/tmp/bbox-wrap-$$" rc=0
  [ -d "${src}" ] || { echo "wrap_in_engine: ${src} is not a directory" >&2; return 1; }
  docker exec "${N8N_CONTAINER}" sh -c "rm -rf '${box}' && mkdir -p '${box}/tooling' '${box}/src' '${box}/out'" || return 1
  COPYFILE_DISABLE=1 tar -C "${N8N_DIR}/tooling" --exclude=node_modules --exclude=test -cf - . \
    | docker exec -i "${N8N_CONTAINER}" tar -C "${box}/tooling" -xf - || rc=1
  if [ "${rc}" = 0 ]; then
    COPYFILE_DISABLE=1 tar -C "${src}" -cf - . | docker exec -i "${N8N_CONTAINER}" tar -C "${box}/src" -xf - || rc=1
  fi
  [ "${rc}" = 0 ] && { docker exec -e BBOX_WRAP_CACHE=1 -w "${box}" "${N8N_CONTAINER}" \
                         node "${box}/tooling/wrap.mjs" "${verb}" "${box}/src" "${box}/out" || rc=1; }
  if [ "${rc}" = 0 ]; then
    mkdir -p "${out}" && docker exec "${N8N_CONTAINER}" tar -C "${box}/out" -cf - . | tar -C "${out}" --no-same-owner -xf - || rc=1
  fi
  docker exec "${N8N_CONTAINER}" rm -rf "${box}" >/dev/null 2>&1 || true
  return "${rc}"
}

wrap_run() {
  local _n
  # bbox_node dies when there is no node here: inside `if` that is the else branch, not the hook's end
  if _n="$(bbox_node 2>/dev/null)"; then
    "${_n}" "${WRAP}" "$@"
  else
    wrap_in_engine "$@"
  fi
}
