"use client";

import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type WheelEvent as ReactWheelEvent } from "react";
import useSWR from "swr";
import {
  CrosshairMode,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  Expand,
  LocateFixed,
  RefreshCw,
  ScanSearch,
  Shrink,
} from "lucide-react";

type CandleRow = {
  time: number;
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type MarkerRow = {
  time: number;
  position: "aboveBar" | "belowBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle";
  text: string;
};

type IndicatorPoint = {
  time: number;
  value: number;
};

type OverlayLine = {
  price: number;
  label: string;
  kind: string;
  color: string;
  lineStyle?: number;
  strength?: number;
  timeframe_source?: string;
  touch_count?: number;
  confidence?: number;
  side_implication?: string;
};

type TradeEvent = {
  kind: "trade";
  trade_id?: string;
  symbol?: string;
  side: string;
  strategy_type?: string;
  timeframe_band?: string | null;
  entry_time?: string;
  entry_time_unix?: number | null;
  exit_time?: string;
  exit_time_unix?: number | null;
  entry_price?: number;
  exit_price?: number;
  stop_price?: number;
  active_stop_price?: number;
  score?: number;
  score_bucket?: string;
  capital_lane?: string;
  risk_group?: string;
  pnl?: number;
  pnl_r?: number;
  exit_reason?: string;
  trail_state?: string;
  convexity_state?: string;
  pyramid_level?: number;
  holding_bars?: number;
  explanation?: string;
};

type DecisionCondition = {
  label: string;
  value: string;
  passed: boolean;
};

type DecisionEvent = {
  kind: "decision";
  timestamp?: string;
  time_unix?: number | null;
  symbol?: string;
  side: string;
  strategy_type?: string;
  timeframe_band?: string | null;
  accepted: boolean;
  final_reason: string;
  score?: number;
  score_bucket?: string;
  threshold?: number;
  capital_lane?: string;
  allocation_rank?: string | number;
  allocation_priority?: number;
  blocking_constraint?: string;
  conditions: DecisionCondition[];
  explanation?: string;
};

type CandlePayload = {
  symbol: string;
  timeframe: string;
  source_path: string;
  source_role?: string;
  closed_candle_policy?: string;
  candles: CandleRow[];
  markers: MarkerRow[];
  trade_events: TradeEvent[];
  decision_events: DecisionEvent[];
  indicators: {
    ema_20: IndicatorPoint[];
    ema_50: IndicatorPoint[];
    vwap_display: IndicatorPoint[];
  };
  structure_levels?: OverlayLine[];
  liquidity_levels?: OverlayLine[];
  visual_live_extension?: Record<string, unknown>;
  replay_checkpoint_timestamp?: string | null;
  window_start_timestamp?: string | null;
  window_end_timestamp?: string | null;
  debug?: Record<string, unknown>;
};

type TimelineEvent =
  | {
      id: string;
      type: "trade-entry" | "trade-exit";
      time: number;
      headline: string;
      colorClass: string;
      trade: TradeEvent;
    }
  | {
      id: string;
      type: "decision";
      time: number;
      headline: string;
      colorClass: string;
      decision: DecisionEvent;
    };

const fetcher = async <T,>(url: string): Promise<T> => {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
};

function formatFlexibleTime(value?: string | number | null) {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  const rawValue = String(value);
  const normalizedValue = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(rawValue)
    ? `${rawValue}Z`
    : rawValue;
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(normalizedValue);
  if (Number.isNaN(date.getTime())) {
    return rawValue;
  }
  const pad = (item: number) => String(item).padStart(2, "0");
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())} UTC`;
}

function formatMetric(value: number | undefined, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "n/a";
  }
  return value.toFixed(digits);
}

function compactMachineText(value: unknown, maxLength = 44) {
  const raw = String(value ?? "n/a");
  if (raw.length <= maxLength) return raw;
  return `${raw.slice(0, Math.max(8, maxLength - 1))}…`;
}

function toUtcTimestamp(value?: number | null): UTCTimestamp | null {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return null;
  }
  return Number(value) as UTCTimestamp;
}

function buildTimelineEvents(payload?: CandlePayload): TimelineEvent[] {
  if (!payload) {
    return [];
  }
  const events: TimelineEvent[] = [];
  for (const trade of payload.trade_events ?? []) {
    if (trade.entry_time_unix) {
      events.push({
        id: `${trade.trade_id ?? trade.entry_time}-entry`,
        type: "trade-entry",
        time: trade.entry_time_unix,
        headline: `${trade.strategy_type ?? "trade"} ${trade.side} entry`,
        colorClass: trade.side === "short" ? "text-orange-200" : "text-emerald-200",
        trade,
      });
    }
    if (trade.exit_time_unix) {
      events.push({
        id: `${trade.trade_id ?? trade.exit_time}-exit`,
        type: "trade-exit",
        time: trade.exit_time_unix,
        headline: `${trade.strategy_type ?? "trade"} exit`,
        colorClass: (trade.pnl ?? 0) >= 0 ? "text-emerald-200" : "text-rose-200",
        trade,
      });
    }
  }
  for (const decision of payload.decision_events ?? []) {
    if (!decision.time_unix) {
      continue;
    }
    events.push({
      id: `${decision.timestamp}-${decision.strategy_type}-${decision.side}-${decision.final_reason}`,
      type: "decision",
      time: decision.time_unix,
      headline: decision.accepted
        ? `${decision.strategy_type ?? "decision"} opened`
        : `${decision.strategy_type ?? "decision"} rejected`,
      colorClass: decision.accepted ? "text-cyan-200" : "text-amber-200",
      decision,
    });
  }
  events.sort((left, right) => right.time - left.time);
  return events;
}

export function CandlePanel({
  symbol,
  timeframe,
  apiUrl,
  untilTime,
  runId,
  mode = "paper",
  endpointPath = "/api/candles",
  panelLabel = "Replay Decision Chart",
}: {
  symbol: string;
  timeframe: string;
  apiUrl: string;
  untilTime?: number | null;
  runId?: string | null;
  mode?: string;
  endpointPath?: string;
  panelLabel?: string;
}) {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showIndicators, setShowIndicators] = useState(true);
  const [showVolume, setShowVolume] = useState(true);
  const [showTrades, setShowTrades] = useState(true);
  const [showRejected, setShowRejected] = useState(false);
  const [showStructure, setShowStructure] = useState(true);
  const [showLiquidity, setShowLiquidity] = useState(true);
  const [followReplay, setFollowReplay] = useState(true);
  const [lookback, setLookback] = useState(180);
  const [lockPriceScale, setLockPriceScale] = useState(false);
  const [verticalScaleMode, setVerticalScaleMode] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [hoverCandle, setHoverCandle] = useState<CandleRow | null>(null);

  const panelRef = useRef<HTMLDivElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const ema50SeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const priceLinesRef = useRef<any[]>([]);
  const viewKeyRef = useRef<string>("");
  const lastClipRef = useRef<number | null>(null);
  const candlesRef = useRef<CandleRow[]>([]);
  const timelineEventsRef = useRef<TimelineEvent[]>([]);
  const lockPriceScaleRef = useRef(false);
  const priceScaleDragCleanupRef = useRef<(() => void) | null>(null);
  const autoFitFrameRef = useRef<number | null>(null);

  const url = useMemo(() => {
    const params = new URLSearchParams({
      symbol,
      timeframe,
      limit: String(lookback),
      mode,
    });
    if (runId) {
      params.set("run_id", runId);
    }
    if (typeof untilTime === "number" && !Number.isNaN(untilTime)) {
      params.set("until_time", String(untilTime));
    }
    return `${apiUrl}${endpointPath}?${params.toString()}`;
  }, [apiUrl, endpointPath, lookback, mode, runId, symbol, timeframe, untilTime]);

  const { data, error, isLoading, mutate } = useSWR<CandlePayload>(url, fetcher, {
    refreshInterval: mode === "structural_lab" ? 5000 : 10000,
    revalidateOnFocus: false,
  });

  const filteredCandles = useMemo(() => {
    if (!data?.candles) {
      return [] as CandleRow[];
    }
    return data.candles.filter((candle) =>
      typeof untilTime === "number" && !Number.isNaN(untilTime) ? candle.time <= untilTime : true,
    );
  }, [data?.candles, untilTime]);

  const filteredMarkers = useMemo(() => {
    if (!data?.markers) {
      return [] as MarkerRow[];
    }
    const firstCandleTime = filteredCandles[0]?.time ?? null;
    const lastCandleTime = filteredCandles[filteredCandles.length - 1]?.time ?? null;
    return data.markers.filter((marker) => {
      const markerText = String(marker.text ?? "").toLowerCase();
      if (
        firstCandleTime !== null &&
        lastCandleTime !== null &&
        (marker.time < firstCandleTime || marker.time > lastCandleTime)
      ) {
        return false;
      }
      if (typeof untilTime === "number" && !Number.isNaN(untilTime) && marker.time > untilTime) {
        return false;
      }
      if (!showTrades && !markerText.includes("rejected")) {
        return false;
      }
      if (!showRejected && markerText.includes("rejected")) {
        return false;
      }
      return true;
    }).sort((left, right) => left.time - right.time);
  }, [data?.markers, filteredCandles, showRejected, showTrades, untilTime]);

  const timelineEvents = useMemo(() => buildTimelineEvents(data), [data]);
  const selectedEvent = useMemo(
    () => timelineEvents.find((event) => event.id === selectedEventId) ?? timelineEvents[0] ?? null,
    [selectedEventId, timelineEvents],
  );

  useEffect(() => {
    setSelectedEventId((current) => current ?? (timelineEvents[0]?.id ?? null));
  }, [timelineEvents]);

  useEffect(() => {
    candlesRef.current = filteredCandles;
  }, [filteredCandles]);

  useEffect(() => {
    timelineEventsRef.current = timelineEvents;
  }, [timelineEvents]);

  useEffect(() => {
    lockPriceScaleRef.current = lockPriceScale;
  }, [lockPriceScale]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === panelRef.current);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  const toggleFullscreen = async () => {
    try {
      if (isFullscreen || document.fullscreenElement === panelRef.current) {
        await document.exitFullscreen();
        setIsFullscreen(false);
        return;
      }
      setIsFullscreen(true);
      await panelRef.current?.requestFullscreen();
    } catch {
      // Keep the dashboard-level fixed overlay even if the browser blocks OS fullscreen.
      setIsFullscreen(true);
    }
  };

  const getInternalPriceScaleHandles = () => {
    const chart = chartRef.current as
      | (IChartApi & {
          _private__chartWidget?: {
            _internal_model?: () => {
              _internal_panes?: () => any[];
              _internal_defaultVisiblePriceScale?: () => any;
              _internal_findPriceScale?: (id: string) => { _internal_priceScale: any } | null;
              _internal_resetPriceScale?: (priceScale: any) => void;
              _internal_lightUpdate?: () => void;
            };
          };
        })
      | null;
    const chartWidget = chart?._private__chartWidget;
    const model = chartWidget?._internal_model?.();
    const pane = model?._internal_panes?.()?.[0] ?? null;
    const priceScale =
      model?._internal_defaultVisiblePriceScale?.() ??
      model?._internal_findPriceScale?.("right")?._internal_priceScale ??
      null;
    if (!chartWidget || !model || !pane || !priceScale) {
      return null;
    }
    return { chartWidget, model, pane, priceScale };
  };

  const getVisibleCandles = () => {
    const candles = candlesRef.current;
    if (!candles.length) {
      return [] as CandleRow[];
    }
    const logicalRange = chartRef.current?.timeScale().getVisibleLogicalRange();
    if (!logicalRange) {
      return candles;
    }
    const from = Math.max(0, Math.floor(logicalRange.from));
    const to = Math.min(candles.length - 1, Math.ceil(logicalRange.to));
    if (to < from) {
      return candles;
    }
    return candles.slice(from, to + 1);
  };

  const setManualPriceRange = (minValue: number, maxValue: number, shouldLock = true) => {
    const handles = getInternalPriceScaleHandles();
    const priceScaleApi = chartRef.current?.priceScale("right");
    const currentRange = handles?.priceScale?._internal_priceRange?.();
    const RangeConstructor = currentRange?.constructor;
    if (!handles || !priceScaleApi || !currentRange || typeof RangeConstructor !== "function") {
      return false;
    }
    const span = Math.max(maxValue - minValue, Math.abs(maxValue || minValue) * 0.001, 1e-9);
    const nextRange = new RangeConstructor(minValue, minValue + span);
    priceScaleApi.applyOptions({ autoScale: false });
    handles.priceScale._internal_setPriceRange?.(nextRange, true);
    handles.model._internal_lightUpdate?.();
    if (shouldLock && !lockPriceScaleRef.current) {
      setLockPriceScale(true);
    }
    return true;
  };

  const fitPriceRangeToCandles = (candles: CandleRow[], lockAfterFit = false) => {
    if (!candles.length) {
      return false;
    }
    let minValue = Number.POSITIVE_INFINITY;
    let maxValue = Number.NEGATIVE_INFINITY;
    for (const candle of candles) {
      if (Number.isFinite(candle.low)) {
        minValue = Math.min(minValue, candle.low);
      }
      if (Number.isFinite(candle.high)) {
        maxValue = Math.max(maxValue, candle.high);
      }
    }
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
      return false;
    }
    const span = Math.max(maxValue - minValue, Math.abs(maxValue || minValue) * 0.004, 1e-6);
    const padding = Math.max(span * 0.08, Math.abs(maxValue || minValue) * 0.001, 1e-6);
    const applied = setManualPriceRange(minValue - padding, maxValue + padding, lockAfterFit);
    if (!applied && !lockAfterFit) {
      chartRef.current?.priceScale("right").applyOptions({ autoScale: true });
    }
    return applied;
  };

  const fitVisiblePriceRange = (lockAfterFit = false) => {
    const visibleCandles = getVisibleCandles();
    return fitPriceRangeToCandles(visibleCandles.length ? visibleCandles : candlesRef.current, lockAfterFit);
  };

  const scalePriceRange = (deltaY: number, anchorY?: number) => {
    const handles = getInternalPriceScaleHandles();
    const currentRange = handles?.priceScale?._internal_priceRange?.();
    const priceScaleApi = chartRef.current?.priceScale("right");
    const rect = containerRef.current?.getBoundingClientRect();
    if (!handles || !currentRange || !priceScaleApi || !rect) {
      return;
    }
    const minValue = currentRange._internal_minValue?.();
    const maxValue = currentRange._internal_maxValue?.();
    if (!Number.isFinite(minValue) || !Number.isFinite(maxValue)) {
      return;
    }
    const height = Math.max(rect.height, 1);
    const anchorRatio = anchorY === undefined ? 0.5 : Math.max(0.05, Math.min(0.95, anchorY / height));
    const anchorPrice = maxValue - (maxValue - minValue) * anchorRatio;
    const scaleCoeff = Math.max(0.15, Math.min(6, Math.exp(deltaY * 0.0065)));
    const nextMin = anchorPrice - (anchorPrice - minValue) * scaleCoeff;
    const nextMax = anchorPrice + (maxValue - anchorPrice) * scaleCoeff;
    priceScaleApi.applyOptions({ autoScale: false });
    if (setManualPriceRange(nextMin, nextMax, true)) {
      handles.model._internal_lightUpdate?.();
    }
  };

  const queueVisibleAutoFit = () => {
    if (lockPriceScaleRef.current) {
      return;
    }
    if (autoFitFrameRef.current !== null) {
      cancelAnimationFrame(autoFitFrameRef.current);
    }
    autoFitFrameRef.current = requestAnimationFrame(() => {
      autoFitFrameRef.current = null;
      void fitVisiblePriceRange(false);
    });
  };

  const setPriceScaleLocked = (nextLocked: boolean) => {
    const priceScaleApi = chartRef.current?.priceScale("right");
    if (!priceScaleApi) {
      setLockPriceScale(nextLocked);
      return;
    }
    if (nextLocked) {
      priceScaleApi.applyOptions({ autoScale: false });
    } else {
      priceScaleApi.applyOptions({ autoScale: false });
    }
    setLockPriceScale(nextLocked);
    if (!nextLocked) {
      queueVisibleAutoFit();
    }
  };

  const resetPriceScale = (preserveLock = false, visibleOnly = false) => {
    const handles = getInternalPriceScaleHandles();
    const priceScaleApi = chartRef.current?.priceScale("right");
    if (!handles || !priceScaleApi) {
      return;
    }
    const shouldRelock = preserveLock && lockPriceScaleRef.current;
    priceScaleApi.applyOptions({ autoScale: false });
    if (visibleOnly) {
      fitVisiblePriceRange(shouldRelock);
    } else {
      handles.model._internal_resetPriceScale?.(handles.priceScale);
    }
    if (shouldRelock) {
      priceScaleApi.applyOptions({ autoScale: false });
    } else if (!visibleOnly) {
      fitVisiblePriceRange(false);
    }
    handles.model._internal_lightUpdate?.();
  };

  const performPriceScaleZoom = (anchorY: number, nextY: number) => {
    scalePriceRange(nextY - anchorY, anchorY);
  };

  const handleChartWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey) {
      return;
    }
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    event.preventDefault();
    const localY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    const scaleOffset = Math.max(-180, Math.min(180, event.deltaY));
    performPriceScaleZoom(localY, localY + scaleOffset);
  };

  const handlePriceScaleWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const localY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    const scaleOffset = Math.max(-180, Math.min(180, event.deltaY));
    performPriceScaleZoom(localY, localY + scaleOffset);
  };

  const handlePriceScaleMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    priceScaleDragCleanupRef.current?.();
    const initialY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    if (!lockPriceScaleRef.current) {
      setLockPriceScale(true);
    }
    const onMove = (moveEvent: MouseEvent) => {
      const currentRect = containerRef.current?.getBoundingClientRect();
      if (!currentRect) {
        return;
      }
      const localY = Math.max(0, Math.min(currentRect.height, moveEvent.clientY - currentRect.top));
      scalePriceRange(localY - initialY, initialY);
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      priceScaleDragCleanupRef.current = null;
    };
    priceScaleDragCleanupRef.current = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      priceScaleDragCleanupRef.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const handleChartMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!verticalScaleMode && !event.altKey) {
      return;
    }
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    priceScaleDragCleanupRef.current?.();
    const initialY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
    if (!lockPriceScaleRef.current) {
      setLockPriceScale(true);
    }
    const onMove = (moveEvent: MouseEvent) => {
      const currentRect = containerRef.current?.getBoundingClientRect();
      if (!currentRect) {
        return;
      }
      moveEvent.preventDefault();
      const localY = Math.max(0, Math.min(currentRect.height, moveEvent.clientY - currentRect.top));
      scalePriceRange(localY - initialY, initialY);
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      priceScaleDragCleanupRef.current = null;
    };
    priceScaleDragCleanupRef.current = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      priceScaleDragCleanupRef.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#030712" },
        textColor: "#cbd5e1",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.08)" },
        horzLines: { color: "rgba(148, 163, 184, 0.08)" },
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 620,
      autoSize: false,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(83, 242, 255, 0.42)" },
        horzLine: { color: "rgba(83, 242, 255, 0.2)" },
      },
      rightPriceScale: {
        borderColor: "rgba(148, 163, 184, 0.18)",
        minimumWidth: 92,
        entireTextOnly: true,
        ticksVisible: true,
        scaleMargins: { top: 0.08, bottom: 0.24 },
      },
      timeScale: {
        borderColor: "rgba(148, 163, 184, 0.18)",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 6,
        barSpacing: 10,
      },
      handleScale: {
        mouseWheel: true,
        pinch: true,
        axisPressedMouseMove: { time: true, price: true },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      wickUpColor: "#86efac",
      wickDownColor: "#fb7185",
      borderVisible: false,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.72, bottom: 0.0 },
    });
    const ema20Series = chart.addLineSeries({
      color: "#38bdf8",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const ema50Series = chart.addLineSeries({
      color: "#a78bfa",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    const vwapSeries = chart.addLineSeries({
      color: "#f59e0b",
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chartRef.current = chart;
    if (typeof window !== "undefined") {
      (window as any).__rtsActiveChart = chart;
    }
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    ema20SeriesRef.current = ema20Series;
    ema50SeriesRef.current = ema50Series;
    vwapSeriesRef.current = vwapSeries;

    chart.subscribeCrosshairMove((param: any) => {
      const timeValue = typeof param?.time === "number" ? Number(param.time) : null;
      if (!timeValue) {
        return;
      }
      const candle = candlesRef.current.find((row) => row.time === timeValue) ?? null;
      setHoverCandle(candle);
    });

    chart.subscribeClick((param: any) => {
      const timeValue = typeof param?.time === "number" ? Number(param.time) : null;
      if (!timeValue) {
        return;
      }
      const exact = timelineEventsRef.current.find((event) => event.time === timeValue);
      if (exact) {
        setSelectedEventId(exact.id);
      }
    });

    const handleVisibleRangeChange = () => {
      queueVisibleAutoFit();
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || 620,
        });
      }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      ema20SeriesRef.current = null;
      ema50SeriesRef.current = null;
      vwapSeriesRef.current = null;
      priceLinesRef.current = [];
      priceScaleDragCleanupRef.current?.();
      if (autoFitFrameRef.current !== null) {
        cancelAnimationFrame(autoFitFrameRef.current);
        autoFitFrameRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !chartRef.current || !volumeSeriesRef.current) {
      return;
    }

    candleSeriesRef.current.setData(
      filteredCandles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    );
    candleSeriesRef.current.setMarkers(
      filteredMarkers.map((marker) => ({
        ...marker,
        time: marker.time as UTCTimestamp,
      })),
    );
    volumeSeriesRef.current.applyOptions({ visible: showVolume });
    volumeSeriesRef.current.setData(
      filteredCandles.map((candle) => ({
        time: candle.time as UTCTimestamp,
        value: candle.volume,
        color: candle.close >= candle.open ? "rgba(34,197,94,0.68)" : "rgba(239,68,68,0.64)",
      })),
    );
    ema20SeriesRef.current?.applyOptions({ visible: showIndicators });
    ema50SeriesRef.current?.applyOptions({ visible: showIndicators });
    vwapSeriesRef.current?.applyOptions({ visible: showIndicators });
    ema20SeriesRef.current?.setData(
      (data?.indicators?.ema_20 ?? []).map((point) => ({
        time: point.time as UTCTimestamp,
        value: point.value,
      })),
    );
    ema50SeriesRef.current?.setData(
      (data?.indicators?.ema_50 ?? []).map((point) => ({
        time: point.time as UTCTimestamp,
        value: point.value,
      })),
    );
    vwapSeriesRef.current?.setData(
      (data?.indicators?.vwap_display ?? []).map((point) => ({
        time: point.time as UTCTimestamp,
        value: point.value,
      })),
    );

    const nextViewKey = `${mode}:${symbol}:${timeframe}:${runId ?? ""}:${lookback}`;
    const clipChanged = (untilTime ?? null) !== lastClipRef.current;
    if (followReplay && (viewKeyRef.current !== nextViewKey || (mode === "backtest" && clipChanged))) {
      chartRef.current.timeScale().applyOptions({ barSpacing: 7, rightOffset: 8 });
      chartRef.current.timeScale().scrollToRealTime();
      viewKeyRef.current = nextViewKey;
    }
    lastClipRef.current = untilTime ?? null;
    queueVisibleAutoFit();
  }, [
    data?.indicators?.ema_20,
    data?.indicators?.ema_50,
    data?.indicators?.vwap_display,
    filteredCandles,
    filteredMarkers,
    followReplay,
    lookback,
    mode,
    runId,
    showIndicators,
    showVolume,
    symbol,
    timeframe,
    untilTime,
  ]);

  useEffect(() => {
    if (!candleSeriesRef.current) {
      return;
    }
    for (const line of priceLinesRef.current) {
      try {
        candleSeriesRef.current.removePriceLine(line);
      } catch {
        // Ignore removed lines.
      }
    }
    priceLinesRef.current = [];

    const series = candleSeriesRef.current;
    const maybeLines: Array<Record<string, unknown>> = [];
    if (selectedEvent && selectedEvent.type !== "decision") {
      const { trade } = selectedEvent;
      maybeLines.push(
        ...[
          trade.entry_price
            ? {
                price: trade.entry_price,
                color: "rgba(56, 189, 248, 0.95)",
                lineStyle: 0,
                axisLabelVisible: true,
                title: "ENTRY",
              }
            : null,
          trade.stop_price
            ? {
                price: trade.stop_price,
                color: "rgba(239, 68, 68, 0.95)",
                lineStyle: 2,
                axisLabelVisible: true,
                title: "STOP",
              }
            : null,
          trade.active_stop_price && trade.active_stop_price !== trade.stop_price
            ? {
                price: trade.active_stop_price,
                color: "rgba(245, 158, 11, 0.95)",
                lineStyle: 1,
                axisLabelVisible: true,
                title: "TRAIL",
              }
            : null,
          trade.exit_price
            ? {
                price: trade.exit_price,
                color: "rgba(34, 197, 94, 0.95)",
                lineStyle: 2,
                axisLabelVisible: true,
                title: "EXIT",
              }
            : null,
        ].filter(Boolean) as Array<Record<string, unknown>>,
      );
    }

    if (showStructure) {
      for (const line of (data?.structure_levels ?? []).slice(0, 8)) {
        maybeLines.push({
          price: line.price,
          color: line.color,
          lineStyle: line.lineStyle ?? 1,
          axisLabelVisible: true,
          title: String(line.kind ?? "LEVEL").slice(0, 12).toUpperCase(),
        });
      }
    }
    if (showLiquidity) {
      for (const line of (data?.liquidity_levels ?? []).slice(0, 6)) {
        maybeLines.push({
          price: line.price,
          color: line.color,
          lineStyle: line.lineStyle ?? 0,
          axisLabelVisible: true,
          title: String(line.kind ?? "POOL").slice(0, 12).toUpperCase(),
        });
      }
    }

    for (const config of maybeLines) {
      priceLinesRef.current.push(series.createPriceLine(config as any));
    }
  }, [data?.liquidity_levels, data?.structure_levels, selectedEvent, showLiquidity, showStructure]);

  const statusLabel = error
    ? "chart error"
    : isLoading && !data
      ? "loading replay candles"
      : `${filteredCandles.length} candles`;

  const currentCandle = hoverCandle ?? filteredCandles[filteredCandles.length - 1] ?? null;
  const visualLive = data?.visual_live_extension ?? (data?.debug?.["visual_live_extension"] as Record<string, unknown> | undefined) ?? {};
  const visualRowsAdded = Number(visualLive["rows_added_for_display"] ?? 0);
  const latestDisplayCandle = String(visualLive["latest_display_1m_candle"] ?? "");
  const canonicalPersistedCandle = String(visualLive["canonical_latest_persisted_1m_candle"] ?? "");
  const displayLagSeconds = Number(visualLive["display_lag_seconds_to_current_forming_1m_candle"] ?? NaN);
  const visualFetchError = visualLive["fetch_error"] ? String(visualLive["fetch_error"]) : "";

  const visibleTimelineEvents = timelineEvents.slice(0, 18);

  const showLatestTradingWindow = () => {
    const chart = chartRef.current;
    const candles = candlesRef.current;
    if (!chart || candles.length === 0) {
      return;
    }
    chart.timeScale().applyOptions({ barSpacing: 7, rightOffset: 8 });
    chart.timeScale().scrollToRealTime();
    queueVisibleAutoFit();
  };

  const resetView = () => {
    showLatestTradingWindow();
    resetPriceScale(false, true);
    setLockPriceScale(false);
    setFollowReplay(true);
  };

  const fitVisible = () => {
    fitVisiblePriceRange(lockPriceScaleRef.current);
  };

  const autoPriceScale = () => {
    fitVisiblePriceRange(false);
    setLockPriceScale(false);
  };

  return (
    <div
      ref={panelRef}
      className={
        isFullscreen
          ? "fixed inset-0 z-[9999] h-screen w-screen overflow-hidden bg-[#020611] p-3 text-white"
          : "cinematic-card overflow-hidden rounded-[30px] border border-white/10 bg-[#020611] text-white"
      }
    >
      <div className={isFullscreen ? "border-b border-white/8 px-3 py-2" : "border-b border-white/8 px-4 py-3"}>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-[240px]">
            <div className="text-[11px] uppercase tracking-[0.28em] text-cyan-200/75">
              {panelLabel}
            </div>
            <div className="mt-1 text-sm text-white/70">
              {symbol} / {timeframe} / {statusLabel}
            </div>
          </div>
          <div className="flex max-w-[min(70vw,1280px)] items-center gap-2 overflow-x-auto pb-1">
            <button
              type="button"
              onClick={() => setFollowReplay((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                followReplay
                  ? "border-emerald-300/24 bg-emerald-400/12 text-emerald-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              follow replay
            </button>
            <button
              type="button"
              onClick={() => setShowIndicators((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                showIndicators
                  ? "border-cyan-300/24 bg-cyan-400/12 text-cyan-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              indicators
            </button>
            <button
              type="button"
              onClick={() => setShowVolume((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                showVolume
                  ? "border-cyan-300/24 bg-cyan-400/12 text-cyan-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              volume
            </button>
            <button
              type="button"
              onClick={() => setShowTrades((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                showTrades
                  ? "border-cyan-300/24 bg-cyan-400/12 text-cyan-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              trades
            </button>
            <button
              type="button"
              onClick={() => setShowRejected((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                showRejected
                  ? "border-amber-300/24 bg-amber-400/12 text-amber-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              rejects
            </button>
            <button
              type="button"
              onClick={() => setShowStructure((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                showStructure
                  ? "border-emerald-300/24 bg-emerald-400/12 text-emerald-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              structure
            </button>
            <button
              type="button"
              onClick={() => setShowLiquidity((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                showLiquidity
                  ? "border-fuchsia-300/24 bg-fuchsia-400/12 text-fuchsia-100"
                  : "border-white/10 bg-white/5 text-white/65"
              }`}
            >
              liquidity
            </button>
            <label className="holo-button shrink-0 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-white/72">
              lookback
              <select
                className="ml-2 bg-transparent text-white outline-none"
                value={lookback}
                onChange={(event) => setLookback(Number(event.target.value))}
              >
                {[120, 180, 300, 500, 1000].map((value) => (
                  <option key={value} value={value} className="bg-slate-950 text-white">
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void mutate()}
              className="holo-button shrink-0 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white/75"
            >
              <RefreshCw className="mr-1 inline h-3.5 w-3.5" />
              refresh
            </button>
            <button
              type="button"
              onClick={autoPriceScale}
              className="holo-button shrink-0 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white/75"
            >
              <LocateFixed className="mr-1 inline h-3.5 w-3.5" />
              auto price scale
            </button>
            <button
              type="button"
              onClick={fitVisible}
              className="holo-button shrink-0 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white/75"
            >
              <ScanSearch className="mr-1 inline h-3.5 w-3.5" />
              fit visible candles
            </button>
            <button
              type="button"
              onClick={() => setVerticalScaleMode((value) => !value)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                verticalScaleMode
                  ? "border-fuchsia-300/24 bg-fuchsia-400/12 text-fuchsia-100"
                  : "border-white/10 bg-white/5 text-white/75"
              }`}
            >
              vertical scale mode
            </button>
            <button
              type="button"
              onClick={() => setPriceScaleLocked(!lockPriceScale)}
              className={`holo-button shrink-0 rounded-full border px-3 py-1 text-[11px] uppercase tracking-[0.2em] ${
                lockPriceScale
                  ? "border-amber-300/24 bg-amber-400/12 text-amber-100"
                  : "border-white/10 bg-white/5 text-white/75"
              }`}
            >
              lock price scale
            </button>
            <button
              type="button"
              onClick={resetView}
              className="holo-button shrink-0 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-white/75"
            >
              <ScanSearch className="mr-1 inline h-3.5 w-3.5" />
              reset view
            </button>
          </div>
          <button
            type="button"
            onClick={() => void toggleFullscreen()}
            className="holo-button shrink-0 inline-flex items-center gap-2 rounded-full border border-cyan-300/30 bg-[#051827]/88 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.22em] text-cyan-50 shadow-[0_0_28px_rgba(34,211,238,0.18)] backdrop-blur transition hover:border-cyan-200/50 hover:bg-cyan-400/16"
            title={isFullscreen ? "Exit fullscreen chart view" : "Open fullscreen chart view"}
          >
            {isFullscreen ? <Shrink className="h-3.5 w-3.5" /> : <Expand className="h-3.5 w-3.5" />}
            {isFullscreen ? "Exit Full Screen" : "Full Screen"}
          </button>
        </div>
        <div className="hidden">
          <span
            className="rounded-full border border-white/10 bg-white/5 px-3 py-1"
            title="Scroll = time zoom, drag = pan, Ctrl+scroll = price zoom, Alt+drag = price scale, price axis drag = price scale"
          >
            Scroll = time zoom, drag = pan, Ctrl+scroll = price zoom, Alt+drag = price scale, price axis drag = price scale
          </span>
        </div>

        <div className="hidden">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/60">
              checkpoint {formatFlexibleTime(data?.replay_checkpoint_timestamp)}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/60">
              window {`${formatFlexibleTime(data?.window_start_timestamp)} -> ${formatFlexibleTime(data?.window_end_timestamp)}`}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/60">
              source {String(data?.source_role ?? data?.debug?.["source_role"] ?? "latest")}
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/60">
            Candles {String(data?.debug?.["candle_count"] ?? 0)} / trades {String(data?.debug?.["trade_events_count"] ?? 0)} / decisions {String(data?.debug?.["decision_events_count"] ?? 0)} / structure {String(data?.debug?.["structure_level_count"] ?? 0)} / liquidity {String(data?.debug?.["liquidity_level_count"] ?? 0)} / rejected {String(data?.debug?.["rejected_events_count"] ?? 0)}
          </div>
        </div>
        {mode === "structural_lab" ? (
          <div className="mt-2 hidden gap-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-emerald-300/16 bg-emerald-400/10 px-3 py-2 text-xs uppercase tracking-[0.18em] text-emerald-100/82">
              display/live latest {latestDisplayCandle ? formatFlexibleTime(latestDisplayCandle) : "n/a"}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs uppercase tracking-[0.18em] text-white/60">
              persisted latest {canonicalPersistedCandle ? formatFlexibleTime(canonicalPersistedCandle) : "n/a"}
            </div>
            <div className="rounded-2xl border border-cyan-300/16 bg-cyan-400/10 px-3 py-2 text-xs uppercase tracking-[0.18em] text-cyan-100/82">
              public visual rows +{Number.isFinite(visualRowsAdded) ? visualRowsAdded : 0}
            </div>
            <div className={`rounded-2xl border px-3 py-2 text-xs uppercase tracking-[0.18em] ${
              visualFetchError
                ? "border-orange-300/18 bg-orange-400/10 text-orange-100"
                : "border-white/10 bg-white/5 text-white/60"
            }`}>
              {visualFetchError
                ? "visual feed warning"
                : `display lag ${Number.isFinite(displayLagSeconds) ? `${Math.round(displayLagSeconds)}s` : "n/a"}`}
            </div>
          </div>
        ) : null}
        <div className="hidden">
          <span className="uppercase tracking-[0.18em] text-white/42">Artifact</span>{" "}
          <span className="break-all text-white/68">{data?.source_path ?? "n/a"}</span>
          <span className="ml-2 text-white/40">| {String(data?.closed_candle_policy ?? data?.debug?.["closed_candle_policy"] ?? "policy unknown")}</span>
        </div>
      </div>

      <div className={isFullscreen ? "grid h-[calc(100vh-82px)] grid-cols-1" : "grid min-h-[780px] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]"}>
        <div className="relative min-h-[680px] border-r border-white/8">
          <div
            className={isFullscreen ? "relative h-[calc(100vh-82px)] w-full" : "relative h-[780px] w-full"}
            onWheel={handleChartWheel}
            onMouseDown={handleChartMouseDown}
          >
            <div ref={containerRef} className="h-full w-full" />
            <div
              className="absolute inset-y-0 right-0 z-20 w-[96px] cursor-ns-resize bg-transparent"
              onMouseDown={handlePriceScaleMouseDown}
              onWheel={handlePriceScaleWheel}
              title="Drag or scroll this price scale to stretch or compress candle height."
            />
          </div>

          <div className="pointer-events-none absolute left-4 top-4 rounded-2xl border border-white/10 bg-[#020611]/86 px-3 py-2 text-xs text-white/78 backdrop-blur">
            <div className="font-medium text-white/92">{currentCandle ? formatFlexibleTime(currentCandle.timestamp) : "awaiting candle"}</div>
            <div className="mt-1 grid grid-cols-3 gap-x-3 gap-y-1 uppercase tracking-[0.14em] text-white/56">
              <span>O {formatMetric(currentCandle?.open)}</span>
              <span>H {formatMetric(currentCandle?.high)}</span>
              <span>L {formatMetric(currentCandle?.low)}</span>
              <span>C {formatMetric(currentCandle?.close)}</span>
              <span>V {formatMetric(currentCandle?.volume, 0)}</span>
              <span>{lockPriceScale ? "scale locked" : showIndicators ? "EMA/VWAP on" : "EMA/VWAP off"}</span>
            </div>
          </div>

          {!isFullscreen && selectedEvent ? (
            <div className="absolute bottom-4 right-4 max-w-[360px] rounded-[24px] border border-white/12 bg-[#06101f]/92 p-4 shadow-[0_24px_60px_rgba(2,6,17,0.5)] backdrop-blur">
              <div className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/72">Pinned Decision</div>
              <div className={`mt-2 text-base font-semibold ${selectedEvent.colorClass}`}>{selectedEvent.headline}</div>
              <div className="mt-1 text-sm text-white/58">{formatFlexibleTime(selectedEvent.time)}</div>
              {selectedEvent.type === "decision" ? (
                <p className="mt-3 text-sm leading-6 text-white/72">{selectedEvent.decision.explanation}</p>
              ) : (
                <p className="mt-3 text-sm leading-6 text-white/72">{selectedEvent.trade.explanation}</p>
              )}
            </div>
          ) : null}

          {isLoading && !data ? (
            <div className="absolute inset-0 flex items-center justify-center bg-[#020611]/74 backdrop-blur-sm">
              <div className="rounded-2xl border border-cyan-300/20 bg-cyan-400/10 px-5 py-3 text-sm uppercase tracking-[0.22em] text-cyan-100">
                Loading replay candles...
              </div>
            </div>
          ) : null}
          {error ? (
            <div className="absolute inset-0 flex items-center justify-center bg-[#020611]/82 backdrop-blur-sm">
              <div className="max-w-lg rounded-2xl border border-orange-300/24 bg-orange-400/10 px-5 py-3 text-center text-sm text-orange-100">
                Chart data request failed. The cockpit stayed read-only; refresh this panel or relaunch the backtest cockpit.
              </div>
            </div>
          ) : null}
          {!isLoading && !error && filteredCandles.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center bg-[#020611]/76 backdrop-blur-sm">
              <div className="max-w-lg rounded-2xl border border-white/12 bg-white/5 px-5 py-3 text-center text-sm text-white/72">
                No candles were returned for the active replay checkpoint. Check the symbol, timeframe, or replay boundary.
              </div>
            </div>
          ) : null}
        </div>

        {!isFullscreen ? (
          <aside className="flex min-h-[640px] flex-col">
            <div className="border-b border-white/8 px-4 py-4">
              <div className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/72">Condition Card</div>
              {selectedEvent ? (
                <div className="mt-3 space-y-3">
                  <div>
                    <div className={`break-words text-base font-semibold ${selectedEvent.colorClass}`} title={selectedEvent.headline}>
                      {compactMachineText(selectedEvent.headline, 42)}
                    </div>
                    <div className="mt-1 text-sm text-white/55">{formatFlexibleTime(selectedEvent.time)}</div>
                  </div>
                  {selectedEvent.type === "decision" ? (
                    <>
                      <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          side {selectedEvent.decision.side}
                        </div>
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          score {formatMetric(selectedEvent.decision.score, 3)}
                        </div>
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          bucket {selectedEvent.decision.score_bucket ?? "n/a"}
                        </div>
                        <div
                          className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72"
                          title={selectedEvent.decision.final_reason}
                        >
                          allocator {compactMachineText(selectedEvent.decision.final_reason, 34)}
                        </div>
                      </div>
                      <p className="text-sm leading-6 text-white/72">{selectedEvent.decision.explanation}</p>
                      <div className="space-y-2">
                        {(selectedEvent.decision.conditions ?? []).map((condition) => (
                          <div
                            key={`${selectedEvent.id}-${condition.label}`}
                            className={`rounded-2xl border px-3 py-2 text-sm ${
                              condition.passed
                                ? "border-emerald-400/18 bg-emerald-400/10 text-emerald-100"
                                : "border-orange-400/18 bg-orange-400/10 text-orange-100"
                            }`}
                          >
                            <div className="text-[10px] uppercase tracking-[0.18em] text-white/55">{condition.label}</div>
                            <div className="mt-1 break-words">{condition.value}</div>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          side {selectedEvent.trade.side}
                        </div>
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          pnl {formatMetric(selectedEvent.trade.pnl)}
                        </div>
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          R {formatMetric(selectedEvent.trade.pnl_r)}
                        </div>
                        <div className="min-w-0 break-words rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          exit {selectedEvent.trade.exit_reason ?? "n/a"}
                        </div>
                      </div>
                      <p className="text-sm leading-6 text-white/72">{selectedEvent.trade.explanation}</p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          entry {formatMetric(selectedEvent.trade.entry_price)}
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          stop {formatMetric(selectedEvent.trade.stop_price)}
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          trail {selectedEvent.trade.trail_state ?? "n/a"}
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white/72">
                          lane {selectedEvent.trade.capital_lane ?? "n/a"}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div className="mt-3 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/60">
                  Click a marker or event in the tape to pin its explanation.
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-4">
              <div className="mb-3 text-[11px] uppercase tracking-[0.24em] text-cyan-200/72">Event Tape</div>
              <div className="space-y-2">
                {visibleTimelineEvents.length ? (
                  visibleTimelineEvents.map((event) => (
                    <button
                      key={event.id}
                      type="button"
                      onClick={() => setSelectedEventId(event.id)}
                      className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                        selectedEvent?.id === event.id
                          ? "border-cyan-300/26 bg-cyan-400/10"
                          : "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/8"
                      }`}
                    >
                      <div className={`text-sm font-medium ${event.colorClass}`}>{event.headline}</div>
                      <div className="mt-1 text-xs uppercase tracking-[0.16em] text-white/45">
                        {formatFlexibleTime(event.time)}
                      </div>
                      <div className="mt-2 break-words text-sm text-white/65">
                        {event.type === "decision"
                          ? compactMachineText(event.decision.final_reason, 52)
                          : `${event.trade.strategy_type ?? "trade"} / ${event.trade.exit_reason ?? "in-flight"}`}
                      </div>
                    </button>
                  ))
                ) : (
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/60">
                    No trade or rejection events were loaded in the visible replay window.
                  </div>
                )}
              </div>
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
