# Package README

This folder contains the Python package for the Crypto Compounding Engine:

- market-data ingestion and resampling
- frozen research/runtime strategy modules
- USDT-signal to USDC-execution bridge logic
- guarded Binance Spot canary execution
- email/reporting helpers
- runtime diagnostics and tests

This file is intentionally short to avoid conflicting documentation.

For the full production explanation, current status, Hetzner deployment layout,
USDT vs USDC decision, safety contract, runbooks, and final operating verdict,
read the root project README:

[`../README.md`](../README.md)

Operational rule: the root README is the authoritative document for this
repository. Package/module files should document local code behavior only.
