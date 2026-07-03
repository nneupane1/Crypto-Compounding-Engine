# Hetzner Docker Deployment Notes

Target starter server: Hetzner CPX22 Regular Performance VPS.

Recommended baseline:

- CPX22 / x86 / Falkenstein / 2 vCPU / 4 GB RAM / 80 GB SSD
- Ubuntu LTS, preferably Ubuntu 24.04 LTS for conservative Docker compatibility
- Docker Engine + Docker Compose plugin
- firewall allowing SSH and, later, HTTPS only
- dashboard bound to localhost until a reverse proxy with auth is installed
- no extra volume, no paid backup, no load balancer, no object storage unless
  deliberately added later

Initial server steps:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

Clone and start:

```bash
git clone <NEW_PRODUCTION_REPO_URL> Retail-Trading-System-Production
cd Retail-Trading-System-Production
cp .env.example .env
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml up -d runtime dashboard-api dashboard
```

Operational checks:

```bash
docker compose -f deploy/docker-compose.prod.yml ps
docker compose -f deploy/docker-compose.prod.yml logs --tail=200 runtime
docker compose -f deploy/docker-compose.prod.yml exec dashboard-api python -m compileall -q /app
curl http://127.0.0.1:8000/health
```

Persistent state lives in Docker volumes:

- `rts_output`
- `rts_data`

The image includes only lightweight runtime seed files. It does not include the
local 8-year research archives.
