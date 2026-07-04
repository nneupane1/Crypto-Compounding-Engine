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
- guarded Binance Spot mainnet tiny-smoke harness for execution plumbing only;
- guarded Binance Spot mainnet live-strategy canary bridge for tiny capped
  fresh-signal execution only;
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

The seed is guarded by
`structural_compounding_lab/runtime_seed/output/multi_symbol_forward_runtime_earned_parallel_slots/checkpoints/historical_warm_start_manifest.json`.
That manifest marks the packaged candles as context memory only. The runtime may
use them for indicators, structure, 15m/1h/6h context, and catch-up continuity,
but it must not count pre-activation seed candles as forward PnL, trade events,
or notification triggers.

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

## Tiny live Spot smoke

The tiny live smoke harness is isolated behind the `live-smoke` Docker Compose
profile. It is not connected to the strategy scheduler and does not approve full
live trading.

Read the runbook before using it:

`docs/LIVE_TINY_SMOKE_RUNBOOK.md`

Default hard caps:

- max account capital for the smoke: `€1,000`
- max test budget: `€50`
- max single order notional: `€10`
- max daily loss cap: `€15`
- Spot only, no margin, no futures, no short selling, no withdrawal code

The harness accepts only dedicated `BINANCE_LIVE_SMOKE_*` keys. Generic live
keys and demo/testnet keys are rejected.

## Tiny live strategy canary

The live strategy canary is isolated behind the `live-canary` Docker Compose
profile. It reads the frozen nine-symbol runtime decision ledger and can submit
only one tiny capped Spot order when all explicit safety confirmations are
present.

Read the runbook before using it:

`docs/LIVE_STRATEGY_CANARY_RUNBOOK.md`

Default behavior is dry-run only:

```bash
docker compose -f deploy/docker-compose.prod.yml --profile live-canary run --rm live-canary
```

This profile does not enable full live trading. It rejects short selling,
margin, futures, withdrawals, generic keys, demo keys, and historical backlog
replay by default.
