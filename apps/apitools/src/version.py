# Single source of truth for the apitools release version.
#
# WHY THIS EXISTS: the running container's code is BAKED at image build time, and a
# stale image is indistinguishable from a fresh one from the outside (same tag, same
# env). We spent a day chasing a fake OCR "regression" that was really an old image.
# Every API response now carries this version so the extraction UI — and any log —
# states exactly which apitools answered. Bump on every behavior-affecting change.
APITOOLS_VERSION = "0.6.3"
