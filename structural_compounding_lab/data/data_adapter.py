from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.config import StructuralLabConfig


def _parse_storage_timestamp(value: str) -> pd.Timestamp:
    return pd.Timestamp(str(value).replace("T", " ").replace(".", ":"))


_RULE_ALIASES = {
    "1m": "1min",
    "3m": "3min",
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "12h": "12h",
    "1d": "1D",
    "1w": "1W",
}


def _coerce_timestamp(value: Any, *, index: pd.DatetimeIndex | None = None, end_of_day: bool = False) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if index is not None and len(index) > 0:
        if index.tz is None and timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        elif index.tz is not None and timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(index.tz)
        elif index.tz is not None and timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(index.tz)
    if end_of_day and isinstance(value, str) and len(value.strip()) == 10:
        timestamp = timestamp + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)
    return timestamp


def _load_structural_csv(path: Path) -> pd.DataFrame:
    print(f"Loading: {path}")
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame.set_index("timestamp", inplace=True)
    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=[column for column in numeric_columns if column in frame.columns])


@dataclass
class StructuralDataAdapter:
    config: StructuralLabConfig

    def __init__(self, config: StructuralLabConfig | None = None) -> None:
        self.config = config or StructuralLabConfig.load()

    def _storage_folder(self, symbol: str) -> Path:
        base = self.config.path("data", "base_path")
        if base is None:
            raise ValueError("data.base_path is not configured")
        return base / symbol / self.config.require("data", "default_interval")

    def resolve_history_file(self, symbol: str, source_csv: str | Path | None = None) -> Path:
        if source_csv is not None:
            path = Path(source_csv)
            if not path.is_absolute():
                path = self.config.lab_root / path
            if not path.exists():
                raise FileNotFoundError(f"Structural source csv does not exist: {path}")
            return path

        symbol = symbol.upper()
        folder = self._storage_folder(symbol)
        if not folder.exists():
            raise FileNotFoundError(f"No local history folder for {symbol}: {folder}")
        start_date = self.config.require("data", "history_start_date")
        end_date = self.config.require("data", "history_end_date")
        exact_path = folder / f"{symbol}_{self.config.require('data', 'default_interval')}_{start_date}_to_{end_date}.csv"
        if exact_path.exists():
            return exact_path

        requested_start = pd.Timestamp(start_date)
        requested_end = pd.Timestamp(end_date)
        prefix = f"{symbol}_{self.config.require('data', 'default_interval')}_"
        candidates: list[tuple[pd.Timestamp, pd.Timestamp, Path]] = []
        for candidate in folder.glob(f"{symbol}_{self.config.require('data', 'default_interval')}_*.csv"):
            stem = candidate.stem
            if not stem.startswith(prefix) or "_to_" not in stem:
                continue
            remainder = stem[len(prefix):]
            start_text, end_text = remainder.split("_to_", 1)
            try:
                candidate_start = _parse_storage_timestamp(start_text)
                candidate_end = _parse_storage_timestamp(end_text)
            except Exception:
                continue
            if candidate_end >= requested_start and candidate_start <= requested_end:
                candidates.append((candidate_end, candidate_start, candidate))
        if not candidates:
            raise FileNotFoundError(f"No local history csv matches {symbol} in {folder}")
        candidates.sort(reverse=True)
        return candidates[0][2]

    def load_base_1m(self, symbol: str, source_csv: str | Path | None = None) -> pd.DataFrame:
        path = self.resolve_history_file(symbol, source_csv=source_csv)
        frame = _load_structural_csv(path)
        frame = frame.sort_index()
        frame = frame[~frame.index.duplicated(keep="last")]
        return self.slice_to_analysis_window(frame)

    def analysis_bounds(self, frame: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
        if frame.empty:
            return None, None
        start_value = (
            self.config.get("data", "analysis_start_date")
            or self.config.get("data", "history_start_date")
        )
        end_value = (
            self.config.get("data", "analysis_end_date")
            or self.config.get("data", "history_end_date")
        )
        index = pd.DatetimeIndex(frame.index)
        start = _coerce_timestamp(start_value, index=index) if start_value else None
        end = _coerce_timestamp(end_value, index=index, end_of_day=True) if end_value else None
        return start, end

    def slice_to_analysis_window(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        start, end = self.analysis_bounds(frame)
        working = frame
        if start is not None:
            working = working.loc[working.index >= start]
        if end is not None:
            working = working.loc[working.index <= end]
        return working.copy()

    def resample(self, frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        normalized = timeframe.lower()
        rule = _RULE_ALIASES.get(normalized, timeframe)
        if normalized in {"1m", "1min"}:
            return frame.copy()
        resampled = (
            frame.resample(rule, closed="left", label="right")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna()
        )
        base_offset = pd.tseries.frequencies.to_offset("1min")
        close_cutoff = frame.index.max() + base_offset
        return resampled.loc[resampled.index <= close_cutoff]

    def build_timeframe_bundle(
        self,
        symbol: str,
        *,
        source_csv: str | Path | None = None,
        timeframes: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        requested = timeframes or [
            "1m",
            self.config.require("execution_timeframe"),
            *self.config.require("confirmation_timeframes"),
        ]
        unique = []
        for timeframe in requested:
            if timeframe not in unique:
                unique.append(timeframe)
        base = self.load_base_1m(symbol, source_csv=source_csv)
        bundle = {"1m": base}
        for timeframe in unique:
            if timeframe == "1m":
                continue
            bundle[timeframe] = self.resample(base, timeframe)
        return bundle


def load_timeframe_bundle(
    symbol: str,
    *,
    config: StructuralLabConfig | None = None,
    source_csv: str | Path | None = None,
    timeframes: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    adapter = StructuralDataAdapter(config=config)
    return adapter.build_timeframe_bundle(symbol, source_csv=source_csv, timeframes=timeframes)
