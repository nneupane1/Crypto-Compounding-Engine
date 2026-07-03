# Retail Trading System Production Runtime

This repository is the production-oriented extraction of the local research
workspace. It is designed for a small Hetzner VPS and Docker Compose.

Current target server baseline:

- Hetzner CPX22 Regular Performance
- Falkenstein
- 2 vCPU / 4 GB RAM / 80 GB SSD
- Docker Compose runtime, API, and production dashboard
- no full historical research archives shipped

It intentionally excludes:

- full historical CSV archives;
- backtest and validation output trees;
- local virtual environments;
- Next.js development cache;
- node modules;
- private `.env` files;
- research court artifacts that are not required by the active runtime.

The active production runtime is:

- nine-symbol public Binance `1m` fetch/catch-up;
- resampling to higher timeframes;
- frozen long-only multi-symbol scanner evaluation;
- output-only research/shadow-forward PnL ledgering;
- optional Binance Spot Testnet demo execution bridge;
- lightweight read-only dashboard API and Next.js production dashboard.

Safety defaults:

- `paper_validation_ready=false`
- `live_allowed=false`
- `real_money_allowed=false`
- `short_selling_allowed=false`
- no production order path is enabled by default

The production scheduler seeds itself from
`structural_compounding_lab/runtime_seed/` on first boot. That seed contains
recent runtime context only; full historical CSV archives remain excluded.

## Local smoke run

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.prod.yml build
docker compose -f deploy/docker-compose.prod.yml up -d runtime dashboard-api dashboard
docker compose -f deploy/docker-compose.prod.yml logs -f runtime
```

Dashboard:

```text
http://127.0.0.1:3000/structural-lab
```

API:

```text
http://127.0.0.1:8000/health
```

## Demo execution bridge

The demo bridge is isolated behind a Docker Compose profile and disabled by
default. It uses Binance Spot Testnet only.

```bash
WALK_FORWARD_DEMO_EXECUTION_ENABLED=true \
docker compose -f deploy/docker-compose.prod.yml --profile demo up -d demo-testnet
```

Do not add production/mainnet keys until a separate live-trading approval and
preflight gate exists.
