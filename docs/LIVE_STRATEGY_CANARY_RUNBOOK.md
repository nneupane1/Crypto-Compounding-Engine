# Live Strategy Canary Runbook

This runbook covers the guarded bridge between the frozen nine-symbol strategy
signal ledger and tiny Binance Spot mainnet execution.

This is not full live trading.

## Purpose

The live canary proves this specific production path:

1. the cloud runtime fetches public Binance `1m` candles;
2. the frozen long-only nine-symbol scanner writes a fresh signal into the
   decision ledger;
3. the live canary reads only that fresh signal;
4. it submits at most one tiny capped Spot buy;
5. it later submits the matching tiny capped Spot sell when the frozen exit
   reference is reached;
6. it writes order/fill/roundtrip artifacts;
7. it sends entry and exit emails.

It does not replay old research signals by default.
It does not enable full strategy live trading.

## Safety defaults

- Spot mainnet only.
- Long-only.
- No short selling.
- No margin.
- No futures.
- No withdrawals.
- No transfers.
- Maximum one open canary position.
- Default account cap: `€100`.
- Default test budget: `€50`.
- Default single-order notional cap: `€10`.
- Default daily loss cap: `€10`.
- Dedicated Binance keys only: `BINANCE_LIVE_SMOKE_API_KEY` and
  `BINANCE_LIVE_SMOKE_API_SECRET`.
- Generic keys and demo keys are rejected inside the container.

The production scheduler remains output-only. The separate live-canary profile
must be invoked explicitly.

## Required Binance key setup

Use a dedicated Binance API key for the tiny live canary:

- enable Reading;
- enable Spot trading;
- disable withdrawals;
- disable margin loan/repay/transfer;
- disable futures-related access;
- restrict access to the Hetzner IPv4 address.

Do not use the future full-capital production key.

## Dry run

Dry run submits no orders.

```bash
cd /opt/crypto-compounding-engine
docker compose -f deploy/docker-compose.prod.yml --profile live-canary run --rm live-canary
```

Expected classifications:

- `BINANCE_LIVE_STRATEGY_CANARY_NO_ELIGIBLE_SIGNAL` when no fresh frozen signal
  is available;
- `BINANCE_LIVE_STRATEGY_CANARY_DRY_RUN_READY_NO_ORDER` when a fresh eligible
  signal is visible, but no order has been submitted.

## Execute once

Run only after dry-run is clean and the operator intentionally accepts the tiny
real-money canary budget.

```bash
cd /opt/crypto-compounding-engine
docker compose -f deploy/docker-compose.prod.yml --profile live-canary run --rm \
  -e RTS_LIVE_CANARY_ENABLED=true \
  -e RTS_LIVE_CANARY_CONFIRM=YES_TINY_REAL_MONEY_STRATEGY_CANARY \
  -e RTS_LIVE_CANARY_I_UNDERSTAND_MAX_LOSS=I_ACCEPT_MAX_25_EUR_LIVE_CANARY_BUDGET \
  live-canary \
  python -m structural_compounding_lab.execution.live_strategy_canary_bridge --mode execute_once
```

If there is no fresh eligible frozen signal, the command exits with no order.
If a fresh signal exists, it may place one tiny capped Spot buy.
If an open canary position exists, it checks the frozen target/stop reference
and may place the matching tiny capped Spot sell.

## Quote balance requirement

The frozen production universe is USDT-quoted:

`ADAUSDT, LINKUSDT, BNBUSDT, XRPUSDT, AVAXUSDT, DOGEUSDT, ETHUSDT, BTCUSDT, SOLUSDT`

The production canary does not buy USDT pairs directly. It uses USDT candles and
signals as the brain, then maps accepted fresh long signals to the matching
USDC Spot pair for execution:

`ADAUSDT -> ADAUSDC`, `BTCUSDT -> BTCUSDC`, etc.

That means the live canary needs a small free USDC balance before it can execute
strategy signals. A EUR balance alone is not enough. For a tiny canary test,
convert only a small amount such as `€30–€100` equivalent to USDC.

## Hetzner timer mode

The recommended production rehearsal runs both pieces on Hetzner:

- Docker `runtime`: fetches public `1m` USDT-quoted candles, resamples
  `15m`/`1h`/`6h`, writes checkpoints, and records frozen shadow signals.
- systemd `rts-live-canary-usdc.timer`: checks the local runtime ledger every
  five minutes and may execute only a fresh tiny USDC canary order.

Install/update the timer:

```bash
cd /opt/crypto-compounding-engine
sudo cp deploy/systemd/rts-live-canary-usdc.service /etc/systemd/system/
sudo cp deploy/systemd/rts-live-canary-usdc.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rts-live-canary-usdc.timer
```

Check it:

```bash
systemctl status rts-live-canary-usdc.timer
systemctl list-timers --all | grep rts-live-canary
cat structural_compounding_lab/output/binance_live_strategy_canary_court_001/latest_status.json
```

## Artifacts

Artifacts are written under:

`structural_compounding_lab/output/binance_live_strategy_canary_court_001/`

Important files:

- `latest_status.json`
- `safety_manifest.json`
- `state/activation_state.json`
- `state/open_position.json`
- `ledger/live_canary_signal_candidates.csv`
- `ledger/live_canary_orders.csv`
- `ledger/live_canary_fills.csv`
- `ledger/live_canary_roundtrips.csv`
- `alerts/latest_live_canary_email.txt`
- `alerts/live_canary_email_ledger.csv`

## Promotion rule

Passing this canary proves only a tiny capped strategy-to-order bridge.

The promotion ladder remains:

1. cloud runtime stable;
2. demo/testnet execution stable;
3. tiny real-money smoke passed;
4. tiny live strategy canary stable;
5. small live allocation;
6. only later larger capital.
