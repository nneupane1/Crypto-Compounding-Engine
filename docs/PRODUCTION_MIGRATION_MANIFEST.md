# Production Migration Manifest

Source workspace:

```text
local research workspace, not shipped to production
```

Production extraction workspace:

```text
local production extraction workspace, copied to the cloud runtime root
```

## Included

- `structural_compounding_lab/` source code needed by the active runtime and
  its package exports.
- `production_runtime/` Docker-friendly scheduler loop.
- `production_api/` lightweight read-only FastAPI telemetry API.
- `dashboard/` source files only, with no `.next` cache and no `node_modules`.
- `deploy/` Dockerfiles and Docker Compose production scaffold.
- `config/settings.json`, because the public Binance fetch helper depends on
  the root runtime config.
- lightweight runtime seeds under
  `structural_compounding_lab/runtime_seed/`.

## Runtime seeds included

The seed folder is intentionally small and exists only to bootstrap the cloud
runtime without shipping full research archives:

- frozen patch rules JSON;
- nine-symbol cap manifest JSON;
- reduced-cap manifest JSON;
- recent multi-symbol runtime candle snapshots for active symbols.

The seed folder is intentionally small enough for Git and large enough to give
the scheduler recent 1m/15m/1H/6H context without shipping full research
archives.

## Excluded

- full historical `data_storage/`;
- `structural_compounding_lab/data_storage/`;
- generated `structural_compounding_lab/output/`;
- local `.env`;
- `.venv*`;
- `dashboard/node_modules`;
- `dashboard/.next`;
- old generated court CSVs/reports unless represented as tiny runtime seed
  JSONs;
- Mac LaunchAgent files.

## Safety posture

The production extraction remains default-disabled for live trading:

- `paper_validation_ready=false`;
- `live_allowed=false`;
- `real_money_allowed=false`;
- production/mainnet Binance keys are not required;
- short selling is disabled;
- Binance Spot Testnet demo is behind an explicit Docker Compose profile and
  `WALK_FORWARD_DEMO_EXECUTION_ENABLED=true`.

## Verified locally

- Python compile/import checks passed.
- Isolated production scheduler smoke passed `GREEN`.
- Isolated production API snapshot/candle checks passed.
- Next.js production build passed before local build artifacts were removed.
- Docker build was not run because the local Docker daemon/Colima was not
  running.
