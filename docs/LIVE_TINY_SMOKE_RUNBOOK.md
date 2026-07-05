# Tiny Live Binance Spot Smoke Runbook

This runbook is for the first real-money execution test only. It is not the production strategy scheduler.

## Current purpose

Prove the cloud can complete a guarded Binance Spot mainnet order lifecycle:

1. read account state,
2. check symbol filters,
3. submit one tiny market buy,
4. submit one immediate market sell,
5. write artifacts,
6. send email,
7. keep the strategy scheduler live path disabled.

## Hard safety limits

- Dedicated env keys only: `BINANCE_LIVE_SMOKE_API_KEY` and `BINANCE_LIVE_SMOKE_API_SECRET`.
- Generic keys are rejected: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BINANCE_SECRET`, `LIVE_API_KEY`, `LIVE_API_SECRET`.
- Demo/testnet keys are rejected inside the live-smoke container.
- Spot only.
- No margin.
- No futures.
- No short selling.
- No withdrawal code.
- One open position maximum.
- Default max account capital for this test: `€1,000`.
- Default max test budget: `€50`.
- Default max order notional: `€10`.
- Default max daily loss: `€15`.
- The production strategy scheduler remains disabled for live orders.

## Binance API key requirements

Create a dedicated Binance API key for this smoke only:

- enable Spot trading,
- disable withdrawals,
- disable margin,
- disable futures,
- restrict the key to Hetzner IPv4 `167.233.138.19`.

Do not reuse demo/testnet keys.
Do not use the future full-capital production key.

## Preflight command

Preflight submits no orders.

```bash
cd /opt/crypto-compounding-engine
docker compose -f deploy/docker-compose.prod.yml --profile live-smoke run --rm live-tiny-smoke
```

Expected ready classification after live-smoke keys are present:

`BINANCE_LIVE_TINY_SMOKE_PREFLIGHT_READY_NO_ORDER`

## Real tiny roundtrip command

Run this only after preflight is ready and the operator intentionally accepts the tiny real-money budget.

```bash
cd /opt/crypto-compounding-engine
docker compose -f deploy/docker-compose.prod.yml --profile live-smoke run --rm \
  -e RTS_LIVE_SMOKE_ENABLED=true \
  -e RTS_LIVE_SMOKE_CONFIRM=YES_TINY_REAL_MONEY_SPOT_SMOKE \
  -e RTS_LIVE_SMOKE_I_UNDERSTAND_MAX_LOSS=I_ACCEPT_MAX_50_EUR_TEST_BUDGET \
  live-tiny-smoke \
  python -m structural_compounding_lab.execution.binance_live_tiny_smoke --mode run_once
```

Expected success classification:

`BINANCE_LIVE_TINY_SMOKE_ORDER_ROUNDTRIP_COMPLETED`

## Artifacts

All artifacts are written under:

`structural_compounding_lab/output/binance_live_tiny_spot_smoke_court_001/`

Important files:

- `latest_status.json`
- `safety_manifest.json`
- `balances_before_after.json`
- `ledger/live_tiny_smoke_orders.csv`
- `ledger/live_tiny_smoke_fills.csv`
- `state/live_tiny_smoke_state.json`
- `alerts/latest_live_tiny_smoke_email.txt`
- `alerts/live_tiny_smoke_email_ledger.csv`

## Deposit rule

Do not add the full intended capital before preflight passes.

For the current EEA/USDC rehearsal, use a USDC-quoted smoke symbol such as
`BTCUSDC`. If the account is funded in EUR, convert only a small amount first,
such as `€30–€100` equivalent to USDC, then run the tiny smoke.

## Promotion rule

Passing this smoke proves only cloud-to-Binance execution plumbing. It does not approve full live trading.

Promotion sequence remains:

1. Hetzner Docker deployment,
2. scheduler/shadow-forward stable,
3. Binance demo/testnet order lifecycle,
4. tiny real-money smoke,
5. small live strategy allocation,
6. only later full planned capital.
