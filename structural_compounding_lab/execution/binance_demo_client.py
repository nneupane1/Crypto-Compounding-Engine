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

from structural_compounding_lab.execution.demo_order_models import DemoMode, DemoOrderIntent, SymbolExecutionRules


SPOT_TESTNET_BASE_URL = "https://testnet.binance.vision/api"
FUTURES_TESTNET_BASE_URL = "https://demo-fapi.binance.com"
ALLOWLISTED_HOSTS = {"testnet.binance.vision", "demo-fapi.binance.com"}
PRODUCTION_HOSTS = {"api.binance.com", "fapi.binance.com", "dapi.binance.com"}
PRODUCTION_PATH_PREFIXES = {("www.binance.com", "/api")}
FORBIDDEN_LIVE_KEY_ENV_NAMES = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
}
REQUIRED_CONFIRMATION = "YES_TESTNET_ONLY"


class BinanceDemoSafetyError(RuntimeError):
    pass


class BinanceDemoExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class BinanceDemoConfig:
    mode: DemoMode
    base_url: str
    api_key: str
    api_secret: str
    recv_window: int = 5000
    timeout_seconds: int = 20

    @property
    def host(self) -> str:
        return urlparse(self.base_url).hostname or ""

    @classmethod
    def from_env(cls, *, require_credentials: bool = True) -> "BinanceDemoConfig":
        reject_live_key_environment()
        confirmation = os.getenv("BINANCE_DEMO_API_TEST_CONFIRM", "")
        if confirmation != REQUIRED_CONFIRMATION:
            raise BinanceDemoSafetyError("BINANCE_DEMO_API_TEST_CONFIRM must equal YES_TESTNET_ONLY")

        mode = os.getenv("BINANCE_DEMO_MODE", "spot_testnet").strip() or "spot_testnet"
        if mode not in {"spot_testnet", "usdm_futures_testnet"}:
            raise BinanceDemoSafetyError(f"Unsupported BINANCE_DEMO_MODE: {mode}")
        if mode == "usdm_futures_testnet" and os.getenv("BINANCE_DEMO_ALLOW_FUTURES_TESTNET", "").lower() not in {"1", "true", "yes"}:
            raise BinanceDemoSafetyError("Futures testnet requires BINANCE_DEMO_ALLOW_FUTURES_TESTNET=true")

        api_key = os.getenv("BINANCE_DEMO_API_KEY", "").strip()
        api_secret = os.getenv("BINANCE_DEMO_API_SECRET", "").strip()
        if require_credentials and (not api_key or not api_secret):
            raise BinanceDemoSafetyError("Missing BINANCE_DEMO_API_KEY or BINANCE_DEMO_API_SECRET")

        base_url = SPOT_TESTNET_BASE_URL if mode == "spot_testnet" else FUTURES_TESTNET_BASE_URL
        validate_base_url(base_url)
        return cls(mode=mode, base_url=base_url, api_key=api_key, api_secret=api_secret)


def reject_live_key_environment() -> None:
    present = [name for name in sorted(FORBIDDEN_LIVE_KEY_ENV_NAMES) if os.getenv(name)]
    if present:
        raise BinanceDemoSafetyError(
            "Refusing Binance demo court because live-looking environment variables are present: "
            + ",".join(present)
        )


def validate_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    path = parsed.path or ""
    if host in PRODUCTION_HOSTS or any(host == item_host and path.startswith(item_path) for item_host, item_path in PRODUCTION_PATH_PREFIXES):
        raise BinanceDemoSafetyError(f"Production Binance endpoint is forbidden: {host}")
    if host not in ALLOWLISTED_HOSTS:
        raise BinanceDemoSafetyError(f"Binance demo host is not allowlisted: {host}")


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


def compute_minimum_quantity(price: Decimal, rules: SymbolExecutionRules) -> Decimal:
    if price <= 0:
        raise ValueError("price must be positive")
    notional_qty = ceil_to_step(rules.min_notional / price, rules.step_size)
    return max(rules.min_qty, notional_qty)


def round_price_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    return floor_to_step(price, tick)


def build_client_order_id(prefix: str, signal_id: str) -> str:
    digest = hashlib.sha256(signal_id.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"[:36]


def decimal_to_plain(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class BinanceDemoClient:
    def __init__(self, config: BinanceDemoConfig) -> None:
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

    def signed_query(self, params: dict[str, Any] | None = None) -> str:
        return urllib.parse.urlencode(self._signed_params(params), doseq=True)

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
            raise BinanceDemoExecutionError(f"http_{exc.code}:{safe}") from exc
        except Exception as exc:  # noqa: BLE001 - court records external API failure
            safe = redact_secret(str(exc), self.config.api_key, self.config.api_secret)
            raise BinanceDemoExecutionError(safe) from exc

    def server_time(self) -> Any:
        path = "/v3/time" if self.config.mode == "spot_testnet" else "/fapi/v1/time"
        return self.request("GET", path)

    def exchange_info(self, symbol: str) -> Any:
        path = "/v3/exchangeInfo" if self.config.mode == "spot_testnet" else "/fapi/v1/exchangeInfo"
        return self.request("GET", path, params={"symbol": symbol.upper()})

    def ticker_price(self, symbol: str) -> Decimal:
        path = "/v3/ticker/price" if self.config.mode == "spot_testnet" else "/fapi/v1/ticker/price"
        payload = self.request("GET", path, params={"symbol": symbol.upper()})
        return Decimal(str(payload["price"]))

    def account(self) -> Any:
        path = "/v3/account" if self.config.mode == "spot_testnet" else "/fapi/v2/account"
        return self.request("GET", path, signed=True)

    def open_orders(self, symbol: str) -> Any:
        path = "/v3/openOrders" if self.config.mode == "spot_testnet" else "/fapi/v1/openOrders"
        return self.request("GET", path, params={"symbol": symbol.upper()}, signed=True)

    def create_order(self, intent: DemoOrderIntent, client_order_id: str) -> Any:
        path = "/v3/order" if self.config.mode == "spot_testnet" else "/fapi/v1/order"
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
        return self.request("POST", path, params=params, signed=True)

    def get_order(self, symbol: str, client_order_id: str | None = None, order_id: str | int | None = None) -> Any:
        path = "/v3/order" if self.config.mode == "spot_testnet" else "/fapi/v1/order"
        params: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id not in {None, ""}:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("client_order_id or order_id is required")
        return self.request("GET", path, params=params, signed=True)

    def cancel_order(self, symbol: str, client_order_id: str | None = None, order_id: str | int | None = None) -> Any:
        path = "/v3/order" if self.config.mode == "spot_testnet" else "/fapi/v1/order"
        params: dict[str, Any] = {"symbol": symbol.upper()}
        if order_id not in {None, ""}:
            params["orderId"] = order_id
        elif client_order_id:
            params["origClientOrderId"] = client_order_id
        else:
            raise ValueError("client_order_id or order_id is required")
        return self.request("DELETE", path, params=params, signed=True)


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
