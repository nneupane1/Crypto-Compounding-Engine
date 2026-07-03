from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Any
from urllib.parse import urlparse

from structural_compounding_lab.execution.demo_order_models import DemoOrderIntent, SymbolExecutionRules


SPOT_MAINNET_BASE_URL = "https://api.binance.com/api"
ALLOWLISTED_HOSTS = {"api.binance.com"}
FORBIDDEN_NON_SPOT_HOSTS = {"fapi.binance.com", "dapi.binance.com", "testnet.binance.vision", "demo-fapi.binance.com"}
REQUIRED_CONFIRMATION = "YES_TINY_REAL_MONEY_SPOT_SMOKE"
FORBIDDEN_GENERIC_LIVE_ENV_NAMES = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
}


class BinanceLiveSpotSafetyError(RuntimeError):
    pass


class BinanceLiveSpotExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BinanceLiveSpotConfig:
    base_url: str
    api_key: str
    api_secret: str
    recv_window: int = 5000
    timeout_seconds: int = 20

    @classmethod
    def from_env(cls, *, require_credentials: bool = True, require_confirmation: bool = False) -> "BinanceLiveSpotConfig":
        if os.getenv("BINANCE_DEMO_API_KEY") or os.getenv("BINANCE_DEMO_API_SECRET"):
            raise BinanceLiveSpotSafetyError("Demo keys must not be used by the live smoke client")
        generic_keys = [key for key in sorted(FORBIDDEN_GENERIC_LIVE_ENV_NAMES) if os.getenv(key)]
        if generic_keys:
            raise BinanceLiveSpotSafetyError(
                "Live smoke requires dedicated BINANCE_LIVE_SMOKE_* keys only; refusing generic key variables: "
                + ",".join(generic_keys)
            )
        if require_confirmation and os.getenv("RTS_LIVE_SMOKE_CONFIRM", "") != REQUIRED_CONFIRMATION:
            raise BinanceLiveSpotSafetyError("RTS_LIVE_SMOKE_CONFIRM must equal YES_TINY_REAL_MONEY_SPOT_SMOKE")

        api_key = os.getenv("BINANCE_LIVE_SMOKE_API_KEY", "").strip()
        api_secret = os.getenv("BINANCE_LIVE_SMOKE_API_SECRET", "").strip()
        if require_credentials and (not api_key or not api_secret):
            raise BinanceLiveSpotSafetyError("Missing BINANCE_LIVE_SMOKE_API_KEY or BINANCE_LIVE_SMOKE_API_SECRET")

        base_url = os.getenv("BINANCE_LIVE_SMOKE_BASE_URL", SPOT_MAINNET_BASE_URL).strip() or SPOT_MAINNET_BASE_URL
        validate_base_url(base_url)
        return cls(base_url=base_url, api_key=api_key, api_secret=api_secret)


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    path = parsed.path or ""
    if host in FORBIDDEN_NON_SPOT_HOSTS:
        raise BinanceLiveSpotSafetyError(f"Non-spot or testnet host is forbidden for live smoke: {host}")
    if host not in ALLOWLISTED_HOSTS:
        raise BinanceLiveSpotSafetyError(f"Live smoke host is not allowlisted: {host}")
    if path.rstrip("/") != "/api":
        raise BinanceLiveSpotSafetyError(f"Live smoke base path must be /api, got: {path}")


def redact_secret(text: str, *secrets: str) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def ceil_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def decimal_to_plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def quantity_for_notional(notional_quote: Decimal, price: Decimal, rules: SymbolExecutionRules) -> Decimal:
    if notional_quote <= 0 or price <= 0:
        raise ValueError("notional and price must be positive")
    raw_qty = notional_quote / price
    qty = floor_to_step(raw_qty, rules.step_size)
    if qty < rules.min_qty:
        qty = rules.min_qty
    if qty * price < rules.min_notional:
        qty = ceil_to_step(rules.min_notional / price, rules.step_size)
    return qty


def build_client_order_id(prefix: str, signal_id: str) -> str:
    digest = hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"[:36]


class BinanceLiveSpotClient:
    def __init__(self, config: BinanceLiveSpotConfig) -> None:
        validate_base_url(config.base_url)
        self.config = config

    def _path(self, path: str) -> str:
        validate_base_url(self.config.base_url)
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.config.base_url}{path}"

    def _signed_params(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(params or {})
        payload.setdefault("recvWindow", self.config.recv_window)
        payload["timestamp"] = int(time.time() * 1000)
        query = urllib.parse.urlencode(payload, doseq=True)
        signature = hmac.new(self.config.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
        payload["signature"] = signature
        return payload

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        payload = self._signed_params(params) if signed else dict(params or {})
        encoded = urllib.parse.urlencode(payload, doseq=True)
        url = self._path(path)
        data = None
        if method.upper() in {"GET", "DELETE"} and encoded:
            url = f"{url}?{encoded}"
        elif encoded:
            data = encoded.encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method.upper())
        if self.config.api_key:
            request.add_header("X-MBX-APIKEY", self.config.api_key)
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")
            safe = redact_secret(body, self.config.api_key, self.config.api_secret)
            raise BinanceLiveSpotExecutionError(f"http_{exc.code}:{safe}") from exc
        except Exception as exc:  # noqa: BLE001
            safe = redact_secret(str(exc), self.config.api_key, self.config.api_secret)
            raise BinanceLiveSpotExecutionError(safe) from exc

    def server_time(self) -> Any:
        return self.request("GET", "/v3/time")

    def exchange_info(self, symbol: str) -> Any:
        return self.request("GET", "/v3/exchangeInfo", params={"symbol": symbol.upper()})

    def ticker_price(self, symbol: str) -> Decimal:
        payload = self.request("GET", "/v3/ticker/price", params={"symbol": symbol.upper()})
        return Decimal(str(payload["price"]))

    def account(self) -> Any:
        return self.request("GET", "/v3/account", signed=True)

    def open_orders(self, symbol: str) -> Any:
        return self.request("GET", "/v3/openOrders", params={"symbol": symbol.upper()}, signed=True)

    def get_order(self, symbol: str, client_order_id: str) -> Any:
        return self.request(
            "GET",
            "/v3/order",
            params={"symbol": symbol.upper(), "origClientOrderId": client_order_id},
            signed=True,
        )

    def create_order(self, intent: DemoOrderIntent, client_order_id: str) -> Any:
        params: dict[str, Any] = {
            "symbol": intent.symbol.upper(),
            "side": intent.side,
            "type": intent.order_type,
            "quantity": decimal_to_plain(intent.quantity),
            "newClientOrderId": client_order_id,
        }
        if intent.order_type == "LIMIT":
            params["timeInForce"] = intent.time_in_force or "GTC"
            params["price"] = decimal_to_plain(intent.price or Decimal("0"))
        return self.request("POST", "/v3/order", params=params, signed=True)


def parse_symbol_rules(exchange_info: dict[str, Any], symbol: str) -> SymbolExecutionRules:
    symbols = exchange_info.get("symbols") or []
    info = next((item for item in symbols if item.get("symbol") == symbol.upper()), None)
    if not info:
        raise ValueError(f"symbol not found in exchangeInfo: {symbol}")
    filters = {item.get("filterType"): item for item in info.get("filters", [])}
    lot = filters.get("LOT_SIZE") or {}
    price_filter = filters.get("PRICE_FILTER") or {}
    min_notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
    return SymbolExecutionRules(
        symbol=symbol.upper(),
        base_asset=info.get("baseAsset", ""),
        quote_asset=info.get("quoteAsset", ""),
        min_qty=Decimal(str(lot.get("minQty", "0.000001"))),
        step_size=Decimal(str(lot.get("stepSize", "0.000001"))),
        tick_size=Decimal(str(price_filter.get("tickSize", "0.01"))),
        min_notional=Decimal(str(min_notional_filter.get("minNotional", min_notional_filter.get("notional", "10")))),
    )
