# GlitchTip - Error Tracking

GlitchTip is an open-source error tracking platform, similar to Sentry. It helps you monitor and debug your applications by collecting error reports, stack traces, and performance data.

## Features

- **Error Tracking**: Collect and organize errors from your applications
- **Stack Traces**: Full stack traces with source context
- **Issue Grouping**: Automatically group similar errors together
- **Team Collaboration**: Multi-user support with organizations and projects
- **Integrations**: Supports Sentry SDKs (JavaScript, Python, etc.)
- **Performance Monitoring**: Track transaction performance
- **Alerts**: Email notifications for new issues

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│    Traefik      │────▶│    GlitchTip     │
│  (Reverse Proxy)│     │   (Web + API)    │
└─────────────────┘     └────────┬─────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐
              │  Postgres │ │  Valkey │ │  Worker   │
              │ (Database)│ │ (Cache) │ │ (Celery)  │
              └───────────┘ └─────────┘ └───────────┘
```

### Services

| Service | Purpose |
|---------|---------|
| `glitchtip` | Main web application (Django) |
| `glitchtip-worker` | Celery worker for background tasks |
| `glitchtip-migrate` | Database migration (runs once on startup) |
| `glitchtip-postgres` | PostgreSQL database |
| `glitchtip-valkey` | Valkey/Redis for caching and task queue |

## URLs

- **Production**: https://glitchtip.hacohen.bina-solutions.co.il
- **Local Development**: http://glitchtip.localhost

## Environment Variables

Add to `.env`:

```bash
# GlitchTip configuration
GLITCHTIP_BASE_URL=glitchtip.hacohen.bina-solutions.co.il
GLITCHTIP_BASE_URL_2=glitchtip2.hacohen.bina-solutions.co.il

# Generate with: openssl rand -hex 32
GLITCHTIP_SECRET_KEY=your-random-secret-key-here

# Database password
GLITCHTIP_DB_PASSWORD=your-secure-database-password

# Email configuration (SMTP format)
# Example: smtp://user:password@smtp.example.com:587
GLITCHTIP_EMAIL_URL=consolemail://
GLITCHTIP_FROM_EMAIL=person3@example.com

# Optional settings
GLITCHTIP_MAX_EVENT_LIFE_DAYS=90
GLITCHTIP_ENABLE_REGISTRATION=true
GLITCHTIP_ENABLE_ORG_CREATION=false
```

## Quick Start

1. Generate secrets:
   ```bash
   # Generate SECRET_KEY
   openssl rand -hex 32
   
   # Generate DB password
   openssl rand -hex 16
   ```

2. Add environment variables to `.env`

3. Deploy:
   ```bash
   docker compose up -d glitchtip glitchtip-worker
   ```

4. Access GlitchTip at https://glitchtip.hacohen.bina-solutions.co.il

5. Create your first user by clicking "Register"

## Usage

### Creating a Project

1. Log in to GlitchTip
2. Create an Organization (if not auto-created)
3. Create a new Project
4. Copy the DSN (Data Source Name)

### Automated Project Setup (Declarative)

For fully automated deployments, use the initialization script to create organizations, teams, and projects via the API:

```bash
# Set required environment variables
export GLITCHTIP_ADMIN_PASSWORD="your-admin-password"
export GLITCHTIP_ADMIN_EMAIL="person192@example.com"
export GLITCHTIP_ORG_NAME="Hacohen"
export GLITCHTIP_TEAM_SLUG="developers"

# Run the initialization script
./init-projects.sh
```

The script will:
1. Wait for GlitchTip to be ready
2. Register/login the admin user
3. Create the organization and team
4. Create all projects defined in the script
5. Output DSNs to `/tmp/glitchtip-dsns.env`

Edit the `PROJECTS` array in `init-projects.sh` to define your projects:
```bash
PROJECTS=(
    "n8n|node"
    "apitools|flask"
    "chat|node"
    "librechat|node"
)
```

#### API Endpoints Reference

GlitchTip provides a full REST API for programmatic management:

| Action | Method | Endpoint |
|--------|--------|----------|
| Create Organization | POST | `/api/0/organizations/` |
| Create Team | POST | `/api/0/organizations/{org}/teams/` |
| Create Project | POST | `/api/0/teams/{org}/{team}/projects/` |
| Get Project Keys (DSN) | GET | `/api/0/projects/{org}/{project}/keys/` |
| API Docs | GET | `/api/docs` |

### SDK Integration Examples

#### JavaScript (Browser)

```javascript
import * as Sentry from "@sentry/browser";

Sentry.init({
  dsn: "https://person193@example.com/1",
  environment: "production"
});
```

#### Python

```python
import sentry_sdk

sentry_sdk.init(
    dsn="https://person193@example.com/1",
    environment="production"
)
```

#### Node.js

```javascript
const Sentry = require("@sentry/node");

Sentry.init({
  dsn: "https://person193@example.com/1",
  environment: "production"
});
```

### Testing Error Reporting

```python
# Python example
import sentry_sdk
sentry_sdk.capture_message("Hello from GlitchTip!")
```

## Maintenance

### Viewing Logs

```bash
# All GlitchTip services
docker compose logs -f glitchtip glitchtip-worker

# Just the worker
docker compose logs -f glitchtip-worker
```

### Database Backup

```bash
docker exec glitchtip-postgres-bina-deployment \
  pg_dump -U glitchtip glitchtip > glitchtip-backup.sql
```

### Database Restore

```bash
docker exec -i glitchtip-postgres-bina-deployment \
  psql -U glitchtip glitchtip < glitchtip-backup.sql
```

### Upgrading

```bash
docker compose pull glitchtip glitchtip-worker
docker compose up -d glitchtip glitchtip-worker
```

Migrations run automatically on container start.

## Troubleshooting

### Check Service Health

```bash
# Check if services are running
docker compose ps | grep glitchtip

# Check health endpoint
curl -s https://glitchtip.hacohen.bina-solutions.co.il/_health/
```

### Common Issues

1. **Migration failed**: Check `glitchtip-migrate` logs
   ```bash
   docker compose logs glitchtip-migrate
   ```

2. **Worker not processing**: Check worker logs
   ```bash
   docker compose logs glitchtip-worker
   ```

3. **Database connection issues**: Verify PostgreSQL is healthy
   ```bash
   docker compose exec glitchtip-postgres pg_isready
   ```

## Resources

- [GlitchTip Documentation](https://glitchtip.com/documentation)
- [GlitchTip GitLab](https://gitlab.com/glitchtip)
- [Sentry SDK Documentation](https://docs.sentry.io/platforms/)
- [Configuration Options](https://glitchtip.com/documentation/install#configuration)

## System Requirements

- **RAM**: 1GB minimum (2GB recommended)
- **Storage**: Varies by usage (~30GB per 1M events/month)
- **CPU**: 1 core minimum (2+ recommended)
