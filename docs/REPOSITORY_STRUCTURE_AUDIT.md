# Repository Structure Audit

This document explains what belongs in the production repository and what does
not. It exists to prevent confusion between the original research workspace and
the separated `Crypto-Compounding-Engine` production repo.

## Current verdict

The repository is a production extraction, not a full local research archive.

It includes:

- source code required by the Hetzner runtime;
- frozen signal-runtime modules;
- guarded Binance Spot smoke/canary execution modules;
- lightweight runtime seed context;
- deployment files;
- read-only dashboard/API source;
- tests and runbooks.

It excludes:

- full 8-year market CSV archives;
- generated runtime output folders;
- local `.env` secrets;
- virtual environments;
- Next.js build cache;
- `node_modules`;
- Python cache files;
- Mac LaunchAgent files;
- local-only historical reports that are not needed for operation.

## Why some research-looking modules remain

The live signal runtime still imports frozen helper functions from historical
court modules. Those imports are part of the evidence chain that produced the
current frozen candidate.

Current active runtime imports include:

| Runtime module | Retained dependency type |
| --- | --- |
| `production_runtime/scheduler_loop.py` | signal runtime entrypoint |
| `structural_compounding_lab/shadow_forward/multi_symbol_forward_runtime.py` | frozen engine, frozen rules, cost-aware helpers, multi-asset court helpers |
| `structural_compounding_lab/execution/live_strategy_canary_bridge.py` | Binance Spot client, USDT→USDC guard, order models, email safety |

Because of that, deleting the whole `diagnostics/` or `backtest/` tree would be
unsafe until those dependencies are extracted into smaller production-native
modules.

## Tracked README policy

Only two first-party README files should exist:

| File | Purpose |
| --- | --- |
| `README.md` | authoritative production overview |
| `structural_compounding_lab/README.md` | short package pointer back to root README |

Dependency README files under installed third-party folders must not be
committed. The production repo should not track `node_modules` anyway.

## Runtime seed policy

`structural_compounding_lab/runtime_seed/` is intentionally tracked.

It is not the generated live output folder. It contains lightweight seed/context
material so the Hetzner runtime can start with enough recent context without
shipping the full historical archive.

Generated live artifacts belong in Docker volumes under:

```text
structural_compounding_lab/output/
data_storage/
```

Those paths are ignored by Git.

## Production identity

The active production identity is:

```text
Crypto Compounding Engine
```

The old local Retail Trading System workspace is no longer the operating
identity of this repository.

The production route is:

```text
USDT signal tape -> frozen 9-symbol long-only scanner -> USDC Spot canary execution
```

Full live €25k deployment remains gated. The current live stage is tiny,
guarded, capped USDC real-money canary validation.
