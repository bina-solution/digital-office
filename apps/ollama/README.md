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

## GPU Support (NVIDIA)

Uncomment in `ollama/docker-compose.yml`:
```yaml
runtime: nvidia
environment:
  - NVIDIA_VISIBLE_DEVICES=all
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
| `OLLAMA_NUM_PARALLEL` | 2 | Number of parallel requests per model |
| `OLLAMA_MAX_LOADED_MODELS` | 2 | Maximum models loaded in memory |
| `OLLAMA_KEEP_ALIVE` | 5m | How long to keep models in memory |

## Resource Limits

Default limits (adjust based on your server):
- CPU: 4 cores (2 reserved)
- Memory: 8GB (4GB reserved)

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
