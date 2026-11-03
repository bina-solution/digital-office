# Ollama Deployment

Production-ready Ollama deployment with Traefik reverse proxy.

## Endpoints

- **Production**: `https://ollama.hacohen.bina-solutions.co.il`
- **Local**: `http://ollama.localhost`

## Security Options

### Option 1: Basic Authentication (Recommended for public access)

1. Generate htpasswd credentials:
   ```bash
   htpasswd -nb admin your_secure_password | sed 's/\$/\$\$/g'
   ```

2. Add to `.env`:
   ```
   OLLAMA_BASIC_AUTH=admin:$$apr1$$xxxxx$$xxxxx
   ```

3. Uncomment in `compose.override.yaml`:
   ```yaml
   - "traefik.http.middlewares.ollama-auth.basicauth.users=${OLLAMA_BASIC_AUTH}"
   - "traefik.http.routers.ollama-https.middlewares=ollama-auth"
   ```

### Option 2: IP Allowlist (For internal/trusted networks)

Uncomment in `compose.override.yaml`:
```yaml
- "traefik.http.middlewares.ollama-ipallowlist.ipallowlist.sourcerange=${DBS_ALLOWED_IPS}"
- "traefik.http.routers.ollama-https.middlewares=ollama-ipallowlist"
```

### Option 3: Both (Maximum security)

Combine both middlewares:
```yaml
- "traefik.http.routers.ollama-https.middlewares=ollama-auth,ollama-ipallowlist"
```

## GPU Support (AMD and Intel, through Vulkan)

The app's image (`Dockerfile`, about 470 MB) carries the release's binary, its CPU backends, its
Vulkan backend and Mesa's Vulkan drivers (RADV for AMD from GCN 1.0 on; ANV/hasvk for Intel). It
leaves CUDA out. To give Ollama the GPU, name the GPU's render node in `.env`:
```bash
for d in /sys/class/drm/renderD*; do echo "$d $(cat $d/device/vendor)"; done   # 0x1002 AMD, 0x8086 Intel
OLLAMA_GPU_DEVICE=/dev/dri/renderD129
```
The container sees that node at the same path. Under another name Vulkan cannot match it. Unset, the
container gets `/dev/null`, and Ollama runs on the CPU. `docker logs ollama-<office>` names the device Ollama found. The Dell
(Radeon R7 M265, GCN 1.0, 4 GiB of VRAM) is measured in DGO-825.

A small GPU needs a smaller context. The context's cache is reserved when a model loads, and what does
not fit on the GPU runs on the CPU. At 32k, qwen3:1.7b's cache took 3.8 GB on the Dell, and 13 of its 29
layers ran on the CPU, at 4–5 tokens/s. At `OLLAMA_CONTEXT_LENGTH=16384` it is 91% on the GPU, and
gemma4:e2b is 100% on the GPU and writes 6.9 tokens/s (DGO-908). `docker logs ollama-<office>` prints
`offloaded N/M layers to GPU` at every load. The offices' agents read the context from the Ollama
itself (`/api/ps`), so no other setting has to follow.

## GPU Support (NVIDIA)

A machine with an NVIDIA GPU needs the upstream image, which carries the CUDA libraries (3.3 GB
compressed).
That is a compose override on that machine, not a variable: `bbox run` builds every service that
has a `build:`, and would tag the CPU build with any name a variable gave it.
```yaml
services:
  ollama:
    build: !reset null
    image: ollama/ollama:0.40.6
    deploy:
      resources:
        reservations:
          devices: [{driver: nvidia, count: all, capabilities: [gpu]}]
```

Ensure NVIDIA Container Toolkit is installed:
```bash
# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

## Usage

### Pull models

The office declares its models in `.env`, and the app pulls the missing ones by itself when it
starts (`entrypoint.sh`). A model that is there is left as it is, so a restart never swaps it for a
newer upload under the same tag. An office that is offline serves what it has:

```bash
OLLAMA_PULL=lfm2.5:8b            # space- or comma-separated library tags
```

Every model that can call tools is then in the office agent's model picker. That covers this
office's Ollama and any linked office's (`apps/bina-ds/tools/llm-routes.mjs`, DGO-825).

By hand, for a one-off:
```bash
# Enter container
docker exec -it ollama-bina-deployment ollama pull llama3.2

# Or via API
curl -X POST https://ollama.hacohen.bina-solutions.co.il/api/pull \
  -d '{"name": "llama3.2"}'
```

### Chat completion
```bash
curl https://ollama.hacohen.bina-solutions.co.il/api/generate \
  -d '{
    "model": "llama3.2",
    "prompt": "Hello, how are you?",
    "stream": false
  }'
```

### List models
```bash
curl https://ollama.hacohen.bina-solutions.co.il/api/tags
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_PULL` | (none) | The models this office holds; pulled on start |
| `OLLAMA_CONTEXT_LENGTH` | 32768 | Context per request. Ollama's own default is 4096, which cuts an agent's prompt silently |
| `OLLAMA_FLASH_ATTENTION` | 1 | Flash attention (also on CPU) |
| `OLLAMA_KV_CACHE_TYPE` | q8_0 | The context's cache at half of f16 (needs flash attention) |
| `OLLAMA_NUM_PARALLEL` | 1 | Number of parallel requests per model; each one holds its own context in memory |
| `OLLAMA_MAX_LOADED_MODELS` | 1 | Maximum models loaded in memory |
| `OLLAMA_KEEP_ALIVE` | 10m | How long to keep models in memory (`-1`: always, on a machine that is there for its models) |
| `OLLAMA_MODELS_DIR` | (the `ollama_data` volume) | A host path for the models, e.g. a disk of their own |
| `OLLAMA_CPUS` / `OLLAMA_MEMORY` | 1.5 / 6G | The container's caps |

## Resource Limits

Default limits are `OLLAMA_CPUS=1.5` and `OLLAMA_MEMORY=6G`. A machine dedicated to its models
gives it every core and most of its memory. The Dell (DGO-825: i7-5500U, 2 cores / 4 threads,
15 GiB, no usable GPU) runs `lfm2.5:8b` with `OLLAMA_CPUS=4.0`, `OLLAMA_MEMORY=11G` and
`OLLAMA_KEEP_ALIVE=-1`.

For production with GPU, consider:
- CPU: 8 cores
- Memory: 16-32GB
- GPU: Full access

## Monitoring

Health check endpoint: `/api/tags`

Check container health:
```bash
docker inspect ollama-bina-deployment --format='{{.State.Health.Status}}'
```

## Integration with n8n

Use the Ollama credentials in n8n with:
- Host: `http://ollama:11434` (internal Docker network)
- Or: `https://ollama.hacohen.bina-solutions.co.il` (external)
