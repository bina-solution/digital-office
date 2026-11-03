# The office's Ollama, for a machine whose GPU (if any) is not an NVIDIA one (DGO-825).
#
# The upstream image is 3.3 GB compressed, of which one 3.1 GB layer is CUDA; unpacked it is more
# than the Dell's whole free disk. This image keeps the release's own binary, its CPU backends (the
# `libggml-cpu-*` variants Ollama picks from at run time) and its VULKAN backend, and leaves CUDA out.
# Vulkan is how an AMD or Intel GPU is used: the runtime stage adds Mesa's Vulkan drivers (RADV runs
# GCN 1.0 and later, conformant since Mesa 24.3), and Ollama uses the GPU when the container is given
# one (compose: OLLAMA_GPU_DEVICE) and falls back to the CPU when it is not. Measured on the Dell
# (Radeon R7 M265, GCN 1.0, 4 GiB): see apps/ollama/README.md.
# The archive is streamed through zstd into tar, so it is never stored. On the way it is hashed and
# checked against the release's own sha256sum.txt: a build of anything else fails.
# The version is HERE and only here (compose passes no build arg), so `bbox` and CI build the same.
FROM ubuntu:24.04 AS fetch
ARG OLLAMA_VERSION=0.40.6
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl zstd \
 && rm -rf /var/lib/apt/lists/*
RUN base="https://github.com/ollama/ollama/releases/download/v${OLLAMA_VERSION}" \
 && want="$(curl -fsSL "${base}/sha256sum.txt" | awk '$2 ~ /(^|\/)ollama-linux-amd64\.tar\.zst$/ {print $1}')" \
 && test -n "${want}" \
 && mkdir -p /out \
 && curl -fsSL "${base}/ollama-linux-amd64.tar.zst" \
  | tee >(sha256sum | cut -d' ' -f1 > /tmp/got) \
  | zstd -dc | tar -x -C /out --wildcards --exclude='lib/ollama/cuda_*' 'bin/*' 'lib/ollama/*' \
 && for i in $(seq 100); do [ -s /tmp/got ] && break; sleep 0.1; done \
 && got="$(cat /tmp/got)" && { [ "${got}" = "${want}" ] || { echo "sha256 ${got} is not the release's ${want}" >&2; exit 1; }; } \
 && test -x /out/bin/ollama && ls /out/lib/ollama/libggml-cpu-*.so >/dev/null \
 && find /out/lib/ollama -iname '*vulkan*' | grep -q . \
 && du -sh /out/lib/ollama/* | sort -h | tail -5

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libvulkan1 mesa-vulkan-drivers \
 && rm -rf /var/lib/apt/lists/*
COPY --from=fetch /out/bin/ollama /usr/bin/ollama
COPY --from=fetch /out/lib/ollama /usr/lib/ollama
ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
ENTRYPOINT ["/usr/bin/ollama"]
CMD ["serve"]
