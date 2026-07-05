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
git clone <NEW_PRODUCTION_REPO_URL> Crypto-Compounding-Engine
cd Crypto-Compounding-Engine
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

Current production rehearsal layout:

- `runtime` container stays running on Hetzner and produces fresh USDT-quoted
  frozen strategy signals from public Binance candles.
- `rts-live-canary-usdc.timer` stays running on Hetzner and checks every five
  minutes for fresh local signals.
- The live canary maps USDT signal symbols to USDC Spot execution symbols and
  uses micro-live hard caps: `47.50 USDC` max order, two open positions, `100 USDC`
  total test budget, `25 USDC` daily closed-loss cap.
- Full live trading remains disabled.

Install the timer after deployment:

```bash
sudo cp deploy/systemd/rts-live-canary-usdc.service /etc/systemd/system/
sudo cp deploy/systemd/rts-live-canary-usdc.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rts-live-canary-usdc.timer
```
