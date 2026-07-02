"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import useSWR from "swr";
import { AnimatePresence, motion } from "framer-motion";
import clsx from "clsx";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BriefcaseBusiness,
  CandlestickChart,
  Clock3,
  Globe,
  LayoutGrid,
  Radar,
  Shield,
  Sparkles,
  Waves,
} from "lucide-react";
import { CandlePanel } from "@/components/candle-panel";
import { MiniLineChart } from "@/components/mini-line-chart";
import { TradeFrequencyPnlPanel, type TradeFrequencyPnlPayload } from "@/components/trade-frequency-pnl-panel";

type Row = Record<string, any>;
type ViewKey = "overview" | "market" | "atlas" | "portfolio" | "allocator" | "runtime";
type DashboardMode = "paper" | "backtest" | "live";

type Snapshot = {
  run?: { run_id: string; path: string; last_write_time?: number } | null;
  portfolio_status: Record<string, any>;
  readiness?: Record<string, any>;
  paper_soak_status?: Record<string, any>;
  paper_soak_daily_report?: Record<string, any>;
  paper_soak_review?: Record<string, any>;
  baseline_freeze_snapshot?: Record<string, any>;
  market_structure_scaffold_inventory?: Record<string, any>;
  capital_refactor_scaffold_inventory?: Record<string, any>;
  capital_refactor_phase1_diagnostics?: Record<string, any>;
  capital_refactor_phase1_evidence_review?: Record<string, any>;
  capital_refactor_master_plan?: Record<string, any>;
  capital_refactor_candidate_registry?: Record<string, any>;
  capital_refactor_validation_ladder?: Record<string, any>;
  capital_refactor_promotion_governance?: Record<string, any>;
  capital_refactor_execution_realism?: Record<string, any>;
  validation_truth?: Record<string, any>;
  artifact_freshness?: Record<string, Record<string, any>>;
  last_runtime_event?: Record<string, any>;
  operator_warning_list?: string[];
  runtime_policy_rows: Row[];
  selection_reason_rows: Row[];
  recent_selection_reason_rows: Row[];
  selection_reason_by_strategy_rows: Row[];
  allocator_decision_rows: Row[];
  daily_summary_rows: Row[];
  trade_rows: Row[];
  trade_frequency_pnl?: TradeFrequencyPnlPayload;
  signal_rows: Row[];
  engine_heartbeat: Record<string, any>;
  engine_cycle_rows: Row[];
  symbol_pipeline_rows: Row[];
  latest_trade?: Row | null;
  latest_signal?: Row | null;
  available_symbols?: string[];
  replay_status?: Record<string, any>;
  replay_checkpoint?: Record<string, any>;
  validation_window?: Record<string, any>;
};

type Point = { label?: string; value: number };

const API_URL = (process.env.NEXT_PUBLIC_DASHBOARD_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const FALLBACK_SYMBOLS = [
  "AAVEUSDT",
  "AVAXUSDT",
  "BNBUSDT",
  "BTCUSDT",
  "ETHUSDT",
  "LINKUSDT",
  "SOLUSDT",
  "TRXUSDT",
  "XRPUSDT",
];

const VIEW_DEFS: {
  key: ViewKey;
  label: string;
  icon: React.ReactNode;
  description: string;
  eyebrow: string;
}[] = [
  {
    key: "overview",
    label: "Overview",
    icon: <BarChart3 className="h-4 w-4" />,
    description: "Role economics, equity rhythm, and multi-sleeve pulse.",
    eyebrow: "Portfolio intelligence",
  },
  {
    key: "market",
    label: "Market",
    icon: <CandlestickChart className="h-4 w-4" />,
    description: "Price, candles, tape, levels, and symbol rotation.",
    eyebrow: "Execution theatre",
  },
  {
    key: "atlas",
    label: "Atlas",
    icon: <LayoutGrid className="h-4 w-4" />,
    description: "Multi-asset, multi-timeframe alignment matrix.",
    eyebrow: "Asset command grid",
  },
  {
    key: "portfolio",
    label: "Portfolio",
    icon: <BriefcaseBusiness className="h-4 w-4" />,
    description: "Blotters, sleeve leaderboard, and exposure context.",
    eyebrow: "Execution book",
  },
  {
    key: "allocator",
    label: "Allocator",
    icon: <Radar className="h-4 w-4" />,
    description: "Cap pressure, suppression reasons, and scarce-risk routing.",
    eyebrow: "Capital routing",
  },
  {
    key: "runtime",
    label: "Runtime",
    icon: <Shield className="h-4 w-4" />,
    description: "Guard health, freshness, recovery, and operator notes.",
    eyebrow: "Operational health",
  },
];

const MODE_META: Record<
  DashboardMode,
  {
    shellLabel: string;
    eyebrow: string;
    description: string;
    accent: string;
    summary: string;
    routeBase: string;
  }
> = {
  paper: {
    shellLabel: "Paper Execution Cockpit",
    eyebrow: "simulated execution rail",
    description: "Live paper telemetry, signal routing, allocator pressure, and chart-level execution flow.",
    accent: "border-sky-300/30 bg-sky-400/14 text-sky-100 shadow-[0_0_18px_rgba(56,189,248,0.12)]",
    summary: "Simulated execution stack consuming live market data with full routing, evaluation, and portfolio telemetry.",
    routeBase: "/paper",
  },
  backtest: {
    shellLabel: "Backtest Intelligence Lab",
    eyebrow: "research replay rail",
    description: "Historical replay, validation artefacts, allocator diagnostics, and strategy forensics.",
    accent: "border-amber-300/30 bg-amber-400/14 text-amber-100 shadow-[0_0_18px_rgba(251,191,36,0.12)]",
    summary: "Historical run analysis tied to the same cockpit language used by paper execution and runtime operations.",
    routeBase: "/backtest",
  },
  live: {
    shellLabel: "Live Operations Deck",
    eyebrow: "runtime command rail",
    description: "Operational readiness, stream health, synchronization, guards, and execution-state observability.",
    accent: "border-emerald-300/28 bg-emerald-400/14 text-emerald-100 shadow-[0_0_18px_rgba(52,211,153,0.12)]",
    summary: "Operational command view aligned to eventual live execution, while consuming the active runtime telemetry rail.",
    routeBase: "/live",
  },
};

function normalizeDashboardMode(value?: string): DashboardMode {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized === "backtest") {
    return "backtest";
  }
  if (normalized === "live") {
    return "live";
  }
  return "paper";
}

function buildViewTabs(mode: DashboardMode) {
  const base = MODE_META[mode].routeBase;
  return VIEW_DEFS.map((tab) => ({
    ...tab,
    href: tab.key === "overview" ? base : `${base}/${tab.key}`,
  }));
}

const fetcher = async <T,>(url: string): Promise<T> => {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
};

function formatMoney(value: unknown) {
  return new Intl.NumberFormat("en-DE", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 2,
  }).format(Number(value ?? 0));
}

function formatPct(value: unknown, digits = 2) {
  return `${(Number(value ?? 0) * 100).toFixed(digits)}%`;
}

function number(value: unknown, digits = 2) {
  return Number(value ?? 0).toFixed(digits);
}

function formatRunTime(value: unknown) {
  if (!value) {
    return "no timestamp";
  }
  const date = new Date(Number(value) * 1000);
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function formatFlexibleTime(value: unknown) {
  if (!value) {
    return "no timestamp";
  }
  if (typeof value === "number") {
    return formatRunTime(value);
  }
  const asNumber = Number(value);
  if (!Number.isNaN(asNumber) && String(value).trim() !== "") {
    return formatRunTime(asNumber);
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function truthy(value: unknown) {
  return String(value).toLowerCase() === "true";
}

function verdictTone(value: unknown): "neutral" | "good" | "warning" {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized === "pass" || normalized === "healthy") {
    return "good";
  }
  if (normalized === "fail" || normalized === "stale" || normalized === "missing" || normalized === "blocker") {
    return "warning";
  }
  return "neutral";
}

function parseRunTimestamp(value: unknown) {
  if (typeof value === "number") {
    return value > 1_000_000_000_000 ? Math.floor(value / 1000) : value;
  }
  if (!value) {
    return null;
  }
  const asNumber = Number(value);
  if (!Number.isNaN(asNumber) && String(value).trim() !== "") {
    return asNumber > 1_000_000_000_000 ? Math.floor(asNumber / 1000) : asNumber;
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  return Math.floor(date.getTime() / 1000);
}

function getReplayTimestamp(snapshot: Snapshot | undefined, selectedSymbol: string) {
  if (!snapshot) {
    return null;
  }
  const dates = [] as Array<number>;

  if (snapshot.replay_checkpoint?.next_candle_time) {
    const parsed = parseRunTimestamp(snapshot.replay_checkpoint.next_candle_time);
    if (parsed) {
      dates.push(parsed);
    }
  }

  if (snapshot.latest_signal?.timestamp) {
    const parsed = parseRunTimestamp(snapshot.latest_signal.timestamp);
    if (parsed) {
      dates.push(parsed);
    }
  }

  if (snapshot.latest_trade?.exit_time) {
    const parsed = parseRunTimestamp(snapshot.latest_trade.exit_time);
    if (parsed) {
      dates.push(parsed);
    }
  }

  if (snapshot.latest_trade?.entry_time) {
    const parsed = parseRunTimestamp(snapshot.latest_trade.entry_time);
    if (parsed) {
      dates.push(parsed);
    }
  }

  const symbolSignal = snapshot.signal_rows
    .filter((row) => String(row.symbol ?? "").toUpperCase() === selectedSymbol.toUpperCase())
    .map((row) => parseRunTimestamp(row.timestamp))
    .filter((value): value is number => typeof value === "number");

  if (symbolSignal.length) {
    dates.push(...symbolSignal);
  }

  if (snapshot.run?.last_write_time) {
    const parsed = parseRunTimestamp(snapshot.run.last_write_time);
    if (parsed) {
      dates.push(parsed);
    }
  }

  return dates.length ? Math.max(...dates) : null;
}

function timeframeBandForStrategy(strategyType: unknown) {
  const key = String(strategyType ?? "").toLowerCase();
  if (!key) {
    return null;
  }
  if (key === "core" || key === "swing_moonshot") {
    return "15m";
  }
  if (key === "h1_execution") {
    return "1h";
  }
  if (key.includes("h6")) {
    return "6h";
  }
  if (key.includes("htf_12h")) {
    return "12h";
  }
  return null;
}

function useLiveSnapshot(mode: DashboardMode) {
  const snapshotUrl = `${API_URL}/api/snapshot?mode=${encodeURIComponent(mode)}`;
  const socketUrl =
    API_URL.replace(/^http/, "ws") +
    (mode === "backtest"
      ? `/ws/backtest?mode=${encodeURIComponent(mode)}`
      : `/ws/live?mode=${encodeURIComponent(mode)}`);

  const { data, mutate } = useSWR<Snapshot>(snapshotUrl, fetcher, {
    refreshInterval: 10000,
    revalidateOnFocus: false,
  });
  const [socketConnected, setSocketConnected] = useState(false);
  const [lastPacketTimestamp, setLastPacketTimestamp] = useState<number | null>(null);

  useEffect(() => {
    const socket = new WebSocket(socketUrl);
    socket.onopen = () => setSocketConnected(true);
    socket.onclose = () => setSocketConnected(false);
    socket.onerror = () => setSocketConnected(false);
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as Snapshot;
        setLastPacketTimestamp(Date.now());
        void mutate(payload, false);
      } catch {
        // Ignore malformed packets.
      }
    };
    return () => socket.close();
  }, [mutate, socketUrl]);

  return {
    data,
    socketConnected,
    lastPacketTimestamp,
  };
}

function SectionCard({
  title,
  eyebrow,
  children,
  className,
  accent = "cyan",
}: {
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
  className?: string;
  accent?: "cyan" | "orange" | "green";
}) {
  const accentClass =
    accent === "orange"
      ? "after:from-orange-400/70 after:to-transparent"
      : accent === "green"
        ? "after:from-emerald-400/70 after:to-transparent"
        : "after:from-cyan-400/70 after:to-transparent";
  const eyebrowClass =
    accent === "orange"
      ? "text-orange-300/75"
      : accent === "green"
        ? "text-emerald-300/75"
        : "text-cyan-300/75";
  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className={clsx(
        "cinematic-card render-contained glass-panel relative overflow-hidden rounded-[28px] border border-white/10 p-5 shadow-glow after:absolute after:inset-x-0 after:top-0 after:h-px after:bg-gradient-to-r",
        accentClass,
        className,
      )}
    >
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          {eyebrow ? (
            <p className={clsx("text-[11px] uppercase tracking-[0.32em]", eyebrowClass)}>{eyebrow}</p>
          ) : null}
          <h2 className="mt-2 text-lg font-semibold text-white">{title}</h2>
        </div>
      </div>
      {children}
    </motion.section>
  );
}

function HeaderMetric({
  label,
  value,
  subtext,
  tone = "neutral",
  points = [],
  pulse = false,
  compact = false,
  className,
}: {
  label: string;
  value: string;
  subtext?: string;
  tone?: "neutral" | "cyan" | "green" | "orange";
  points?: Point[];
  pulse?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const toneClass =
    tone === "cyan"
      ? "border-cyan-300/28 bg-[linear-gradient(180deg,rgba(8,45,62,0.72),rgba(7,19,34,0.9))]"
      : tone === "green"
        ? "border-emerald-300/28 bg-[linear-gradient(180deg,rgba(9,45,38,0.72),rgba(8,20,23,0.9))]"
        : tone === "orange"
          ? "border-orange-300/28 bg-[linear-gradient(180deg,rgba(52,31,18,0.78),rgba(24,16,21,0.92))]"
          : "border-violet-200/18 bg-[linear-gradient(180deg,rgba(34,29,48,0.78),rgba(18,16,29,0.94))]";
  const sparkTone = tone === "neutral" ? "cyan" : tone;
  const sparkPoints = points.length ? points : [{ value: 0 }, { value: 0 }];
  const compactValue = value.length > 18;
  return (
    <div
      className={clsx(
        "cinematic-card flex min-w-0 flex-col justify-between rounded-[22px] border shadow-[0_18px_40px_rgba(0,0,0,0.22)]",
        compact ? "min-h-[76px] px-3 py-2.5" : "px-4 py-3 min-h-[116px]",
        toneClass,
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className={clsx("uppercase text-white/52", compact ? "text-[9px] tracking-[0.24em]" : "text-[10px] tracking-[0.28em]")}>{label}</div>
        </div>
        <div className="flex items-center gap-2">
          <MiniLineChart
            points={sparkPoints}
            tone={sparkTone}
            className={clsx(
              "rounded-full border border-white/14 bg-black/12",
              compact ? "h-[20px] w-[46px]" : "h-[30px] w-[70px]",
            )}
            height={compact ? 22 : 34}
          />
          <span
            className={clsx(
              "inline-flex shrink-0 rounded-full shadow-[0_0_16px_currentColor]",
              compact ? "h-1.5 w-1.5" : "h-2.5 w-2.5",
              tone === "green"
                ? "bg-emerald-300"
                : tone === "orange"
                  ? "bg-orange-300"
                  : tone === "cyan"
                    ? "bg-cyan-300"
                    : "bg-white/50",
              pulse ? "animate-pulse" : "",
            )}
          />
        </div>
      </div>
      <div className={clsx("min-w-0", compact ? "mt-2.5" : "mt-4")}>
        <div
          className={clsx(
            "break-words font-semibold leading-tight text-white",
            compact
              ? compactValue
                ? "text-[13px] md:text-[14px]"
                : "text-[18px]"
              : compactValue
                ? "text-[15px] md:text-base"
                : "text-[26px]",
          )}
        >
          {value}
        </div>
        {subtext ? (
          <div className={clsx("text-white/58", compact ? "mt-1 text-[10px] leading-4" : "mt-2 text-xs leading-5")}>
            {subtext}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  subtext,
  tone = "cyan",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  subtext: string;
  tone?: "cyan" | "orange" | "green";
}) {
  const toneClass =
    tone === "orange"
      ? "from-orange-500/18 to-orange-500/4 border-orange-400/25"
      : tone === "green"
        ? "from-emerald-500/18 to-emerald-500/4 border-emerald-400/25"
        : "from-cyan-500/18 to-cyan-500/4 border-cyan-400/25";
  return (
    <div className={clsx("cinematic-card rounded-2xl border bg-gradient-to-br p-4", toneClass)}>
      <div className="mb-3 flex items-center gap-3 text-white/80">
        <div className="rounded-xl border border-white/10 bg-white/5 p-2">{icon}</div>
        <span className="text-xs uppercase tracking-[0.24em]">{label}</span>
      </div>
      <div className="text-2xl font-semibold text-white">{value}</div>
      <div className="mt-2 text-sm text-white/55">{subtext}</div>
    </div>
  );
}

function StatPill({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "good" | "warning";
}) {
  const toneClass =
    tone === "good"
      ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
      : tone === "warning"
        ? "border-orange-400/20 bg-orange-400/10 text-orange-200"
        : "border-white/10 bg-white/5 text-white";
  return (
    <div className={clsx("rounded-2xl border-2 px-4 py-3", toneClass)}>
      <div className="text-[11px] uppercase tracking-[0.22em] text-white/55">{label}</div>
      <div className="mt-2 text-lg font-semibold">{value}</div>
    </div>
  );
}

function SignalStateCell({
  row,
  label,
}: {
  row?: Row;
  label: string;
}) {
  if (!row) {
    return (
      <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-2">
        <div className="text-[10px] uppercase tracking-[0.2em] text-white/35">{label}</div>
        <div className="mt-2 text-sm text-white/45">idle</div>
      </div>
    );
  }
  const side = String(row.side ?? "flat").toLowerCase();
  const toneClass =
    side === "long"
      ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
      : side === "short"
        ? "border-orange-400/20 bg-orange-400/10 text-orange-200"
        : "border-white/10 bg-white/5 text-white";
  return (
    <div className={clsx("rounded-2xl border px-3 py-2", toneClass)}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-[10px] uppercase tracking-[0.2em] text-white/45">{label}</div>
        <div className="text-[11px] uppercase tracking-[0.18em]">{side}</div>
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="text-base font-semibold">{number(row.selection_score, 2)}</div>
        <div className="max-w-[110px] truncate text-[11px] text-white/55">
          {row.strategy_type}
        </div>
      </div>
    </div>
  );
}

export function DashboardShell({
  view = "overview",
  mode = normalizeDashboardMode(process.env.NEXT_PUBLIC_DASHBOARD_MODE || "paper"),
}: {
  view?: ViewKey;
  mode?: DashboardMode;
}) {
  const dashboardMode = normalizeDashboardMode(mode);
  const modeMeta = MODE_META[dashboardMode];
  const viewTabs = useMemo(() => buildViewTabs(dashboardMode), [dashboardMode]);
  const { data: snapshot, socketConnected, lastPacketTimestamp } = useLiveSnapshot(dashboardMode);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [timeframe, setTimeframe] = useState("15m");

  const portfolio = snapshot?.portfolio_status ?? {};
  const readiness = snapshot?.readiness ?? {};
  const soakStatus = snapshot?.paper_soak_status ?? {};
  const dailySoakReport = snapshot?.paper_soak_daily_report ?? {};
  const soakReview = snapshot?.paper_soak_review ?? {};
  const baselineFreezeSnapshot = snapshot?.baseline_freeze_snapshot ?? {};
  const marketStructureScaffold = snapshot?.market_structure_scaffold_inventory ?? {};
  const capitalRefactorScaffold = snapshot?.capital_refactor_scaffold_inventory ?? {};
  const capitalRefactorDiagnostics = snapshot?.capital_refactor_phase1_diagnostics ?? {};
  const capitalRefactorEvidenceReview = snapshot?.capital_refactor_phase1_evidence_review ?? {};
  const capitalRefactorMasterPlan = snapshot?.capital_refactor_master_plan ?? {};
  const capitalRefactorCandidateRegistry = snapshot?.capital_refactor_candidate_registry ?? {};
  const capitalRefactorValidationLadder = snapshot?.capital_refactor_validation_ladder ?? {};
  const capitalRefactorPromotionGovernance = snapshot?.capital_refactor_promotion_governance ?? {};
  const capitalRefactorExecutionRealism = snapshot?.capital_refactor_execution_realism ?? {};
  const validationTruth = snapshot?.validation_truth ?? {};
  const replayStatus = snapshot?.replay_status ?? {};
  const replayCheckpoint = snapshot?.replay_checkpoint ?? {};
  const validationWindow = snapshot?.validation_window ?? {};
  const artifactFreshness = snapshot?.artifact_freshness ?? {};
  const lastRuntimeEvent = snapshot?.last_runtime_event ?? {};
  const runtimeContext = portfolio.runtime_context ?? {};
  const strategyStats = portfolio.strategy_stats ?? {};
  const selectionRows = snapshot?.selection_reason_rows ?? [];
  const recentSelectionRows = snapshot?.recent_selection_reason_rows ?? [];
  const strategySelectionRows = snapshot?.selection_reason_by_strategy_rows ?? [];
  const allocatorDecisionRows = snapshot?.allocator_decision_rows ?? [];
  const runtimeRows = snapshot?.runtime_policy_rows ?? [];
  const trades = snapshot?.trade_rows ?? [];
  const signals = snapshot?.signal_rows ?? [];
  const engineHeartbeat = snapshot?.engine_heartbeat ?? {};
  const engineCycleRows = snapshot?.engine_cycle_rows ?? [];
  const symbolPipelineRows = snapshot?.symbol_pipeline_rows ?? [];
  const availableSymbols = snapshot?.available_symbols?.length
    ? snapshot.available_symbols
    : FALLBACK_SYMBOLS;

  useEffect(() => {
    if (!availableSymbols.includes(symbol)) {
      setSymbol(availableSymbols[0] ?? "BTCUSDT");
    }
  }, [availableSymbols, symbol]);

  const strategyCards = useMemo(
    () =>
      Object.entries(strategyStats)
        .map(([name, row]) => ({
          name,
          total_pnl: Number((row as Row).total_pnl ?? 0),
          count: Number((row as Row).count ?? 0),
          wins: Number((row as Row).wins ?? 0),
          total_R: Number((row as Row).total_R ?? 0),
        }))
        .sort((a, b) => b.total_pnl - a.total_pnl),
    [strategyStats],
  );

  const equityPoints = useMemo(
    () =>
      (snapshot?.daily_summary_rows ?? []).map((row, index) => ({
        label: String(row.date ?? index),
        value: Number(row.equity_end ?? row.equity_start ?? 0),
      })),
    [snapshot?.daily_summary_rows],
  );

  const pnlPoints = useMemo(
    () =>
      (snapshot?.daily_summary_rows ?? []).map((row, index) => ({
        label: String(row.date ?? index),
        value: Number(row.realized_pnl ?? 0),
      })),
    [snapshot?.daily_summary_rows],
  );

  const capPoints = useMemo(
    () =>
      (recentSelectionRows.length ? recentSelectionRows : selectionRows)
        .slice(0, 10)
        .reverse()
        .map((row, index) => ({
          label: String(row.selection_reason ?? index),
          value: Number(row.count ?? 0),
        })),
    [recentSelectionRows, selectionRows],
  );

  const thresholdPoints = useMemo(
    () =>
      (snapshot?.daily_summary_rows ?? []).map((row, index) => ({
        label: String(row.date ?? index),
        value: Number(row.threshold ?? row.current_threshold ?? 0),
      })),
    [snapshot?.daily_summary_rows],
  );

  const topTradeRows = useMemo(() => trades.slice(-12).reverse(), [trades]);
  const topSignalRows = useMemo(() => signals.slice(-18).reverse(), [signals]);
  const recentCycleTapeRows = useMemo(() => engineCycleRows.slice(-8).reverse(), [engineCycleRows]);
  const recentAllocatorTapeRows = useMemo(() => allocatorDecisionRows.slice(-10).reverse(), [allocatorDecisionRows]);
  const runtimeRow = runtimeRows[0];
  const topSymbols = Array.isArray(portfolio.top_symbols) ? portfolio.top_symbols : [];
  const topSymbolSet = useMemo(() => new Set(topSymbols.map((item: string) => String(item))), [topSymbols]);
  const recentCapPressure = portfolio.cap_pressure_summary?.recent ?? {};
  const cumulativeCapPressure = portfolio.cap_pressure_summary?.cumulative ?? {};
  const livePnl = Number(portfolio.equity ?? 0) - Number(portfolio.initial_equity ?? 0);
  const latestTradePnl = Number(snapshot?.latest_trade?.pnl ?? 0);
  const readinessBlockers = Array.isArray(readiness.blockers) ? readiness.blockers : [];
  const readinessWarnings = Array.isArray(readiness.warnings) ? readiness.warnings : [];
  const operatorWarnings = Array.isArray(snapshot?.operator_warning_list) ? snapshot.operator_warning_list : [];
  const soakWarnings = Array.isArray(soakStatus.display_warning_list)
    ? soakStatus.display_warning_list
    : Array.isArray(soakStatus.warning_list)
      ? soakStatus.warning_list
      : [];
  const activeSleeves = Array.isArray(runtimeContext.active_sleeves) ? runtimeContext.active_sleeves : [];
  const disabledSleeves = Array.isArray(runtimeContext.disabled_sleeves) ? runtimeContext.disabled_sleeves : [];
  const artifactRows = useMemo<Array<Record<string, any>>>(
    () =>
      Object.entries(artifactFreshness).map((entry) => {
        const [key, value] = entry;
        return {
          key,
          ...((value ?? {}) as Record<string, any>),
        };
      }),
    [artifactFreshness],
  );
  const latestAllocatorRejections = soakStatus.latest_allocator_rejection_counts ?? {};
  const strategyTradeCounts = soakStatus.latest_strategy_level_trade_counts ?? {};
  const strategyLevelPnl = soakStatus.latest_strategy_level_pnl ?? {};
  const promotionCriteria = dailySoakReport.promotion_criteria ?? {};
  const promotionStatus = String(promotionCriteria.promotion_status ?? "paper_soak_in_progress");
  const soakReviewCriteria = soakReview.soak_review_criteria ?? {};
  const soakReviewRows = useMemo<Row[]>(
    () =>
      Object.entries(soakReviewCriteria).map(([key, value]) => ({
        key,
        ...((value ?? {}) as Record<string, any>),
      })),
    [soakReviewCriteria],
  );
  const currentMode = String(runtimeContext.mode ?? readiness.requested_mode ?? "unknown");
  const baselineManualReview = baselineFreezeSnapshot.manual_review ?? {};
  const marketStructureModulesPresent = Object.values(marketStructureScaffold.modules_present ?? {}).filter(Boolean).length;
  const capitalRefactorLayerStatuses = capitalRefactorScaffold.layer_statuses ?? {};
  const capitalRefactorLayers = useMemo<Row[]>(
    () =>
      Object.entries(capitalRefactorLayerStatuses).map(([key, value]) => ({
        key,
        ...((value ?? {}) as Row),
      })),
    [capitalRefactorLayerStatuses],
  );
  const capitalRefactorModulesPresent = Object.values(capitalRefactorScaffold.modules_present ?? {}).filter(Boolean).length;
  const capitalDiagnosticsWarnings = Array.isArray(capitalRefactorDiagnostics.warnings) ? capitalRefactorDiagnostics.warnings : [];
  const capitalEvidenceWarnings = Array.isArray(capitalRefactorEvidenceReview.warnings) ? capitalRefactorEvidenceReview.warnings : [];
  const capitalDiagnosticsReports = useMemo<Row[]>(
    () =>
      [
        "capital_refactor_phase1_diagnostics_summary",
        "capital_refactor_phase1_rejection_shadow_book",
        "capital_refactor_phase1_capital_blocked_winners",
        "capital_refactor_phase1_top_winner_forensics",
        "capital_refactor_phase1_strategy_bucket_capital_efficiency",
        "capital_refactor_phase1_opportunity_cost_report",
      ]
        .map((key) => ({
          key,
          ...((artifactFreshness[key] ?? {}) as Row),
        }))
        .filter((row: Row) => row.path || row.exists !== undefined),
    [artifactFreshness],
  );
  const capitalEvidenceReports = useMemo<Row[]>(
    () =>
      [
        "capital_refactor_phase1_evidence_review_json",
        "capital_refactor_phase1_evidence_review_md",
        "capital_refactor_phase2_experiment_brief_md",
        "capital_refactor_phase1_review_status",
      ]
        .map((key) => ({
          key,
          ...((artifactFreshness[key] ?? {}) as Row),
        }))
        .filter((row: Row) => row.path || row.exists !== undefined),
    [artifactFreshness],
  );
  const capitalResearchReports = useMemo<Row[]>(
    () =>
      [
        "capital_refactor_master_plan",
        "capital_refactor_candidate_registry",
        "capital_refactor_validation_ladder",
        "capital_refactor_promotion_governance",
        "capital_refactor_execution_cost_research",
        "capital_refactor_execution_cost_model",
        "capital_refactor_execution_cost_sensitivity",
      ]
        .map((key) => ({
          key,
          ...((artifactFreshness[key] ?? {}) as Row),
        }))
        .filter((row: Row) => row.path || row.exists !== undefined),
    [artifactFreshness],
  );
  const capitalCandidateCount = Number(capitalRefactorCandidateRegistry.candidate_count ?? 0);
  const capitalLadderStages = Array.isArray(capitalRefactorValidationLadder.stages)
    ? capitalRefactorValidationLadder.stages
    : [];
  const capitalMasterLayers = Array.isArray(capitalRefactorMasterPlan.layers)
    ? capitalRefactorMasterPlan.layers
    : [];
  const executionCostScenarioCount = Array.isArray(capitalRefactorExecutionRealism.scenarios)
    ? capitalRefactorExecutionRealism.scenarios.length
    : 0;
  const latestDataTimestamp = validationTruth.latest_data_timestamp ?? readiness.latest_common_data_timestamp;
  const runtimeLastProcessedTimestamp =
    soakStatus.runtime_last_processed_timestamp ?? runtimeContext.runtime_last_processed_timestamp;
  const staleRuntimeDetected =
    soakWarnings.some((item: string) => String(item).includes("stale")) ||
    Number(soakStatus.runtime_boundary_lag_seconds ?? 0) > 300;
  const h1ShortOverrideActive =
    truthy(soakStatus.h1_short_override_active) ||
    Array.isArray(runtimeContext.readiness?.runtime_config?.strategy_allowed_sides?.h1_execution) &&
      runtimeContext.readiness.runtime_config.strategy_allowed_sides.h1_execution.includes("short");
  const h6StandardDisabled = disabledSleeves.includes("h6_standard");
  const h6MoonshotDisabled = disabledSleeves.includes("h6_moonshot");
  const gateArtifactBlockers = Array.isArray(validationTruth.gate_report_blockers) ? validationTruth.gate_report_blockers : [];
  const gateStatusBlockers = Array.isArray(validationTruth.gate_status_blockers) ? validationTruth.gate_status_blockers : [];
  const replayTimestamp = useMemo(() => getReplayTimestamp(snapshot, symbol), [snapshot, symbol]);
  const replayClipTimestamp = useMemo(() => {
    const checkpointTime = replayCheckpoint.next_candle_time ?? replayCheckpoint.updated_at;
    return parseRunTimestamp(checkpointTime);
  }, [replayCheckpoint.next_candle_time, replayCheckpoint.updated_at]);
  const replayProgressPercent = Number(replayCheckpoint.progress_percent ?? 0);
  const replayNextIndex = Number(replayCheckpoint.next_index ?? 0);
  const replayEstimatedBars = Number(replayCheckpoint.estimated_total_bars ?? 0);
  const replayStage = String(replayStatus.stage ?? "idle");
  const replayWindowPolicy = String(validationWindow.window_policy ?? "n/a");
  const liveFeedTimestamp = useMemo(
    () => parseRunTimestamp(engineHeartbeat.latest_recent_1m_timestamp ?? snapshot?.run?.last_write_time),
    [engineHeartbeat.latest_recent_1m_timestamp, snapshot?.run?.last_write_time],
  );
  const chartClipTimestamp = dashboardMode === "backtest" ? replayClipTimestamp : null;
  const connectionLabel =
    dashboardMode === "backtest"
      ? snapshot?.run?.run_id
        ? `replay ${replayStage}`
        : "no run"
      : socketConnected
        ? "stream live"
        : "reconnecting";
  const connectionTone =
    dashboardMode === "backtest" ? (snapshot?.run ? "green" : "orange") : socketConnected ? "green" : "orange";
  const viewMeta = viewTabs.find((item) => item.key === view) ?? viewTabs[0];
  const runtimePoints = useMemo(() => {
    const pf = Number(runtimeRow?.profit_factor ?? 0);
    const avgR = Number(runtimeRow?.avg_R ?? 0);
    const count = Number(runtimeRow?.count ?? 0);
    return [{ value: pf }, { value: avgR * 10 }, { value: count }];
  }, [runtimeRow]);
  const enginePulsePoints = useMemo(
    () =>
      engineCycleRows.slice(-24).map((row, index) => ({
        label: String(row.cycle_count ?? index),
        value: Number(row.candidates_built ?? row.new_15m_symbol_count ?? 0),
      })),
    [engineCycleRows],
  );
  const ingestionPoints = useMemo(
    () =>
      engineCycleRows.slice(-24).map((row, index) => ({
        label: String(row.cycle_count ?? index),
        value: Number(row.total_recent_1m_rows ?? 0),
      })),
    [engineCycleRows],
  );
  const openFlowPoints = useMemo(
    () =>
      engineCycleRows.slice(-24).map((row, index) => ({
        label: String(row.cycle_count ?? index),
        value: Number(row.opened_count ?? 0),
      })),
    [engineCycleRows],
  );
  const pipelineBySymbol = useMemo(() => {
    const map = new Map<string, Row>();
    for (const row of symbolPipelineRows) {
      map.set(String(row.symbol ?? "").toUpperCase(), row);
    }
    return map;
  }, [symbolPipelineRows]);

  const latestTradeBySymbol = useMemo(() => {
    const map = new Map<string, Row>();
    for (let index = trades.length - 1; index >= 0; index -= 1) {
      const row = trades[index];
      const symbolKey = String(row.symbol ?? "").toUpperCase();
      if (!symbolKey || map.has(symbolKey)) {
        continue;
      }
      map.set(symbolKey, row);
    }
    return map;
  }, [trades]);

  const signalBandsBySymbol = useMemo(() => {
    const bandOrder = ["15m", "1h", "6h", "12h"];
    const map = new Map<string, Record<string, Row | undefined>>();
    for (let index = topSignalRows.length - 1; index >= 0; index -= 1) {
      const row = topSignalRows[index];
      const symbolKey = String(row.symbol ?? "").toUpperCase();
      const band = timeframeBandForStrategy(row.strategy_type);
      if (!symbolKey || !band) {
        continue;
      }
      const bucket = map.get(symbolKey) ?? {};
      const current = bucket[band];
      if (!current || Number(row.selection_score ?? 0) >= Number(current.selection_score ?? 0)) {
        bucket[band] = row;
      }
      map.set(symbolKey, bucket);
    }
    for (const item of availableSymbols) {
      if (!map.has(item)) {
        map.set(item, Object.fromEntries(bandOrder.map((band) => [band, undefined])));
      }
    }
    return map;
  }, [availableSymbols, topSignalRows]);

  const symbolAtlasRows = useMemo(
    () =>
      availableSymbols.map((item) => {
        const bands = signalBandsBySymbol.get(item) ?? {};
        const lastTrade = latestTradeBySymbol.get(item);
        const pipeline = pipelineBySymbol.get(item) ?? {};
        return {
          symbol: item,
          isTop: topSymbolSet.has(item),
          pipeline,
          lastTrade,
          lastTradePnl: Number(lastTrade?.pnl ?? 0),
          lastTradeSide: String(lastTrade?.side ?? ""),
          band15m: bands["15m"],
          band1h: bands["1h"],
          band6h: bands["6h"],
          band12h: bands["12h"],
          lastSignalTime:
            bands["15m"]?.timestamp ??
            bands["1h"]?.timestamp ??
            bands["6h"]?.timestamp ??
            bands["12h"]?.timestamp ??
            null,
        };
      }),
    [availableSymbols, latestTradeBySymbol, pipelineBySymbol, signalBandsBySymbol, topSymbolSet],
  );

  const topMoverCards = useMemo(
    () =>
      symbolAtlasRows
        .filter((row) => row.isTop)
        .slice(0, 4),
    [symbolAtlasRows],
  );

  const overviewContent = (
    <div className="grid gap-5">
      <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr_0.95fr]">
        <SectionCard title="Equity Wave" eyebrow="Daily curve" accent="cyan">
          <div className="mb-3 flex items-center justify-between text-sm text-white/55">
            <span>End-of-day equity path</span>
            <span>{equityPoints.length} days</span>
          </div>
          <MiniLineChart points={equityPoints} tone="cyan" className="h-[190px]" />
        </SectionCard>

        <SectionCard title="PnL Rhythm" eyebrow="Realized daily pulse" accent="green">
          <div className="mb-3 flex items-center justify-between text-sm text-white/55">
            <span>Realized PnL by day</span>
            <span>{pnlPoints.length} days</span>
          </div>
          <MiniLineChart points={pnlPoints} tone="green" className="h-[190px]" />
        </SectionCard>

        <SectionCard title="Stack Pulse" eyebrow="System role split" accent="green">
          <div className="grid gap-3 sm:grid-cols-2">
            <StatPill label="Threshold source" value={String(portfolio.current_threshold_source ?? "base")} />
            <StatPill label="Threshold floor" value={number(portfolio.current_threshold_floor, 2)} />
            <StatPill
              label="Recent cap block rate"
              value={formatPct(recentCapPressure.cap_block_rate, 1)}
              tone={(recentCapPressure.cap_block_rate ?? 0) > 0.2 ? "warning" : "good"}
            />
            <StatPill label="Top symbols" value={topSymbols.length ? String(topSymbols.length) : "none"} />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {topSymbols.length ? (
              topSymbols.map((item: string) => (
                <span
                  key={item}
                  className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-cyan-200"
                >
                  {item}
                </span>
              ))
            ) : (
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-white/50">
                no active leaders yet
              </span>
            )}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Engine Pulse" eyebrow="Ingestion / sync / routing" accent="orange">
        <div className="grid gap-5 xl:grid-cols-[0.95fr_0.95fr_1.1fr]">
          <div className="grid gap-3 sm:grid-cols-2">
            <StatPill
              label="Cycle state"
              value={String(engineHeartbeat.status ?? "waiting")}
              tone={String(engineHeartbeat.status ?? "").includes("routed") ? "good" : "neutral"}
            />
            <StatPill label="Cycle" value={String(engineHeartbeat.cycle_count ?? 0)} />
            <StatPill
              label="Latest 1m feed"
              value={formatFlexibleTime(engineHeartbeat.latest_recent_1m_timestamp)}
              tone={engineHeartbeat.latest_recent_1m_timestamp ? "good" : "warning"}
            />
            <StatPill label="New 15m symbols" value={String(engineHeartbeat.new_15m_symbol_count ?? 0)} />
            <StatPill label="Candidates built" value={String(engineHeartbeat.candidates_built ?? 0)} />
            <StatPill label="Opened this cycle" value={String(engineHeartbeat.opened_count ?? 0)} tone={Number(engineHeartbeat.opened_count ?? 0) > 0 ? "good" : "neutral"} />
          </div>
          <div className="grid gap-3">
            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.24em] text-white/45">1m ingestion pressure</div>
              <MiniLineChart points={ingestionPoints} tone="cyan" className="h-[130px]" />
            </div>
            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.24em] text-white/45">Candidate / route pulse</div>
              <MiniLineChart points={enginePulsePoints} tone="orange" className="h-[130px]" />
            </div>
          </div>
          <div className="rounded-3xl border border-white/10 bg-white/[0.04] p-4">
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs uppercase tracking-[0.24em] text-white/45">Current cycle readout</div>
              <span className="rounded-full border border-cyan-400/18 bg-cyan-400/10 px-3 py-1 text-[10px] uppercase tracking-[0.2em] text-cyan-200">
                {String(engineHeartbeat.symbol_count ?? availableSymbols.length)} symbols
              </span>
            </div>
            <div className="mt-4 grid gap-3 text-sm text-white/65">
              <div className="flex items-center justify-between gap-4 rounded-2xl border border-white/8 bg-black/10 px-4 py-3">
                <span>Total recent 1m rows</span>
                <span className="font-semibold text-white">{engineHeartbeat.total_recent_1m_rows ?? 0}</span>
              </div>
              <div className="flex items-center justify-between gap-4 rounded-2xl border border-white/8 bg-black/10 px-4 py-3">
                <span>State rows in memory</span>
                <span className="font-semibold text-white">{engineHeartbeat.total_state_1m_rows ?? 0}</span>
              </div>
              <div className="flex items-center justify-between gap-4 rounded-2xl border border-white/8 bg-black/10 px-4 py-3">
                <span>Opened candidates this cycle</span>
                <span className="font-semibold text-white">{engineHeartbeat.opened_count ?? 0}</span>
              </div>
              <div className="rounded-2xl border border-white/8 bg-black/10 px-4 py-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-white/45">Selection reasons this cycle</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {Object.entries(engineHeartbeat.selection_reason_counts ?? {}).length ? (
                    Object.entries(engineHeartbeat.selection_reason_counts ?? {}).map(([reason, count]) => (
                      <span
                        key={reason}
                        className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[11px] uppercase tracking-[0.14em] text-white/70"
                      >
                        {String(reason)} {String(count)}
                      </span>
                    ))
                  ) : (
                    <span className="text-white/45">No routing reason changes recorded yet.</span>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Sleeve PnL" eyebrow="Role decomposition">
        <div className="grid gap-4 xl:grid-cols-3">
          {strategyCards.length ? (
            strategyCards.map((row) => (
              <div key={row.name} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs uppercase tracking-[0.24em] text-white/45">{row.name}</div>
                    <div className="mt-1 text-lg font-semibold">{formatMoney(row.total_pnl)}</div>
                  </div>
                  <div className="text-right text-sm text-white/60">
                    <div>{row.count} trades</div>
                    <div>{row.wins} wins</div>
                  </div>
                </div>
                <div className="mt-3 text-sm text-white/55">total R {number(row.total_R, 2)}</div>
              </div>
            ))
          ) : (
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
              No sleeve PnL rows yet.
            </div>
          )}
        </div>
      </SectionCard>

      <SectionCard title="Leader Deck" eyebrow="Active market focus" accent="cyan">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {topMoverCards.length ? (
            topMoverCards.map((row) => (
              <div key={row.symbol} className="rounded-2xl border border-cyan-400/18 bg-cyan-400/8 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs uppercase tracking-[0.24em] text-cyan-200/70">{row.symbol}</div>
                    <div className="mt-2 text-lg font-semibold text-white">
                      {row.band15m?.side ?? row.band1h?.side ?? row.band12h?.side ?? "watch"}
                    </div>
                  </div>
                  <span className="rounded-full border border-cyan-300/20 bg-cyan-300/10 px-2 py-1 text-[10px] uppercase tracking-[0.22em] text-cyan-100">
                    top mover
                  </span>
                </div>
                <div className="mt-4 grid gap-2">
                  <SignalStateCell row={row.band15m} label="15m" />
                  <SignalStateCell row={row.band1h} label="1H" />
                  <SignalStateCell row={row.band12h} label="12H" />
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55 md:col-span-2 xl:col-span-4">
              No active leader rows yet.
            </div>
          )}
        </div>
      </SectionCard>
    </div>
  );

  const marketContent = (
    <div className="grid gap-5">
      <SectionCard title="Market Panel" eyebrow="Price / trades / levels" className="min-h-[760px]">
        <div className="mb-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
          <div className="flex flex-wrap gap-2">
          <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.24em] text-white/65">
            {dashboardMode === "backtest"
              ? `Replay clipping through ${formatFlexibleTime(replayClipTimestamp)}`
              : `Live feed through ${formatFlexibleTime(liveFeedTimestamp)}`}
          </div>
          {dashboardMode === "backtest" ? (
            <div className="rounded-2xl border border-amber-400/20 bg-amber-400/10 px-4 py-2 text-xs uppercase tracking-[0.24em] text-amber-200">
              {replayStage} {replayProgressPercent.toFixed(1)}%
            </div>
          ) : null}
          <label className="flex min-w-[170px] flex-col gap-1 rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-3 py-2">
            <span className="text-[10px] uppercase tracking-[0.22em] text-cyan-200/80">Symbol</span>
            <select
              className="rounded-xl border border-white/12 bg-slate-950/90 px-3 py-2 text-sm font-medium text-white outline-none"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
            >
              {availableSymbols.map((item) => (
                <option key={item} value={item} className="bg-slate-950 text-white">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-w-[120px] flex-col gap-1 rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-3 py-2">
            <span className="text-[10px] uppercase tracking-[0.22em] text-cyan-200/80">Timeframe</span>
            <select
              className="rounded-xl border border-white/12 bg-slate-950/90 px-3 py-2 text-sm font-medium text-white outline-none"
              value={timeframe}
              onChange={(event) => setTimeframe(event.target.value)}
            >
              {["1m", "15m", "1h", "6h", "12h", "1D"].map((item) => (
                <option key={item} value={item} className="bg-slate-950 text-white">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-2 text-xs uppercase tracking-[0.24em] text-cyan-200">
            Pan / zoom / price levels / trade markers
          </div>
          <div className={clsx(
            "rounded-2xl px-4 py-2 text-xs uppercase tracking-[0.24em]",
            connectionTone === "green"
              ? "border border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
              : "border border-amber-400/20 bg-amber-400/10 text-amber-200",
          )}>
            {connectionLabel}
          </div>
          </div>
          <div className="flex flex-wrap gap-2 xl:justify-end">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.24em] text-white/60">
              last write {formatRunTime(snapshot?.run?.last_write_time)}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.24em] text-white/60">
              {dashboardMode === "backtest"
                ? `next candle ${formatFlexibleTime(replayClipTimestamp)}`
                : `strategy checkpoint ${formatFlexibleTime(replayTimestamp)}`}
            </div>
          </div>
          </div>
        </div>
        <CandlePanel
          symbol={symbol}
          timeframe={timeframe}
          apiUrl={API_URL}
          untilTime={chartClipTimestamp}
          runId={dashboardMode === "backtest" ? "latest" : snapshot?.run?.run_id ?? undefined}
          mode={dashboardMode}
        />
      </SectionCard>

      <div className="grid gap-5 xl:grid-cols-[0.82fr_1.18fr]">
        <SectionCard title="Trade Tape" eyebrow="Latest exits">
          <div className="space-y-2">
            {topTradeRows.length ? (
              topTradeRows.map((trade, index) => {
                const pnl = Number(trade.pnl ?? 0);
                return (
                  <div
                    key={`${trade.trade_id ?? trade.entry_time ?? index}`}
                    className="grid grid-cols-[1.1fr_0.8fr_0.7fr_0.6fr] items-center rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm"
                  >
                    <div>
                      <div className="font-medium text-white">{trade.symbol}</div>
                      <div className="text-xs uppercase tracking-[0.16em] text-white/45">{trade.strategy_type}</div>
                    </div>
                    <div className="text-white/70">{trade.side}</div>
                    <div className={pnl >= 0 ? "text-emerald-300" : "text-orange-300"}>{formatMoney(pnl)}</div>
                    <div className="text-right text-white/45">{trade.exit_reason || "n/a"}</div>
                  </div>
                );
              })
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No closed trades in the current run yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Symbol Switchboard" eyebrow="Live market roster">
          <div className="grid gap-3 sm:grid-cols-2">
            {symbolAtlasRows.slice(0, 10).map((row) => (
              <button
                key={row.symbol}
                type="button"
                onClick={() => setSymbol(row.symbol)}
                className={clsx(
                  "rounded-2xl border px-4 py-3 text-left transition-all",
                  row.symbol === symbol
                    ? "border-cyan-400/30 bg-cyan-400/12 shadow-glow"
                    : "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/8",
                )}
              >
                <div className="flex items-center justify-between">
                  <div className="text-sm font-semibold text-white">{row.symbol}</div>
                  {row.isTop ? (
                    <span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-cyan-200">
                      leader
                    </span>
                  ) : null}
                </div>
                <div className="mt-3 grid grid-cols-3 gap-2">
                  <SignalStateCell row={row.band15m} label="15m" />
                  <SignalStateCell row={row.band1h} label="1H" />
                  <SignalStateCell row={row.band12h} label="12H" />
                </div>
                <div className="mt-3 flex items-center justify-between text-[11px] uppercase tracking-[0.18em] text-white/45">
                  <span>1m {formatFlexibleTime(row.pipeline.latest_recent_1m_timestamp)}</span>
                  <span>{row.pipeline.candidate_count ?? 0} candidates</span>
                </div>
              </button>
            ))}
          </div>
        </SectionCard>
      </div>
    </div>
  );

  const atlasContent = (
    <div className="grid gap-5">
      <div className="grid gap-5 xl:grid-cols-[1.3fr_0.7fr]">
        <SectionCard title="Asset Atlas" eyebrow="Multi-timeframe alignment matrix" accent="cyan">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-white/45">
                <tr>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">1m feed</th>
                  <th className="pb-3 pr-4 font-medium">Leader</th>
                  <th className="pb-3 pr-4 font-medium">15M</th>
                  <th className="pb-3 pr-4 font-medium">1H</th>
                  <th className="pb-3 pr-4 font-medium">6H</th>
                  <th className="pb-3 pr-4 font-medium">12H</th>
                  <th className="pb-3 pr-4 font-medium">Candidates</th>
                  <th className="pb-3 pr-4 font-medium">Last exit</th>
                </tr>
              </thead>
              <tbody>
                {symbolAtlasRows.map((row) => (
                  <tr key={row.symbol} className="border-t border-white/6 align-top">
                    <td className="py-4 pr-4">
                      <div className="font-semibold text-white">{row.symbol}</div>
                      <div className="mt-1 text-xs uppercase tracking-[0.18em] text-white/35">
                        {row.lastSignalTime ? formatFlexibleTime(row.lastSignalTime) : "awaiting signal"}
                      </div>
                    </td>
                    <td className="py-4 pr-4">
                      <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                        <div className="text-[11px] uppercase tracking-[0.18em] text-white/45">
                          {formatFlexibleTime(row.pipeline.latest_recent_1m_timestamp)}
                        </div>
                        <div className="mt-2 text-xs text-white/60">
                          {row.pipeline.recent_rows_1m ?? 0} fresh / {row.pipeline.state_rows_1m ?? 0} state
                        </div>
                      </div>
                    </td>
                    <td className="py-4 pr-4">
                      {row.isTop ? (
                        <span className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-cyan-200">
                          top
                        </span>
                      ) : (
                        <span className="text-white/35">-</span>
                      )}
                    </td>
                    <td className="py-4 pr-4"><SignalStateCell row={row.band15m} label="15m" /></td>
                    <td className="py-4 pr-4"><SignalStateCell row={row.band1h} label="1H" /></td>
                    <td className="py-4 pr-4"><SignalStateCell row={row.band6h} label="6H" /></td>
                    <td className="py-4 pr-4"><SignalStateCell row={row.band12h} label="12H" /></td>
                    <td className="py-4 pr-4">
                      <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                        <div className="text-sm font-semibold text-white">{row.pipeline.candidate_count ?? 0}</div>
                        <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-white/45">
                          {row.pipeline.candidate_strategies || "none"}
                        </div>
                      </div>
                    </td>
                    <td className="py-4 pr-4">
                      {row.lastTrade ? (
                        <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                          <div className={clsx("text-sm font-semibold", row.lastTradePnl >= 0 ? "text-emerald-300" : "text-orange-300")}>
                            {formatMoney(row.lastTradePnl)}
                          </div>
                          <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-white/45">
                            {row.lastTrade.strategy_type} / {row.lastTradeSide}
                          </div>
                        </div>
                      ) : (
                        <span className="text-white/35">none</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Atlas Notes" eyebrow="How to read the matrix" accent="green">
          <div className="grid gap-4">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-white/60">
              This grid is designed for a multi-role book. `15M` shows tactical flow, `1H` shows the
              specialized short sleeve, `6H` remains a shadow research lane, and `12H` shows structural
              conviction. Rows are meant to be scanned horizontally, not read one symbol at a time.
            </div>
            <StatPill label="Tracked symbols" value={String(availableSymbols.length)} />
            <StatPill label="Active top movers" value={String(topSymbols.length)} tone={topSymbols.length ? "good" : "neutral"} />
            <StatPill label="Latest signal tape" value={String(topSignalRows.length)} />
          </div>
        </SectionCard>
      </div>
    </div>
  );

  const portfolioContent = (
    <div className="grid gap-5">
      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr_0.9fr]">
        <MetricCard
          icon={<BriefcaseBusiness className="h-4 w-4" />}
          label="Open book"
          value={String(portfolio.open_positions ?? 0)}
          subtext={`daily entries ${portfolio.daily_entries_taken ?? 0}`}
          tone="cyan"
        />
        <MetricCard
          icon={<Activity className="h-4 w-4" />}
          label="Live PnL"
          value={formatMoney(livePnl)}
          subtext={`closed today ${formatMoney(portfolio.daily_closed_pnl ?? 0)}`}
          tone={livePnl >= 0 ? "green" : "orange"}
        />
        <MetricCard
          icon={<Sparkles className="h-4 w-4" />}
          label="Top mover roster"
          value={topSymbols.length ? topSymbols.join(" / ") : "idle"}
          subtext={snapshot?.run?.run_id ?? "no run"}
          tone="green"
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.08fr_0.92fr]">
        <SectionCard title="Execution Blotter" eyebrow="Recent closed trades" accent="cyan">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-white/45">
                <tr>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">Strategy</th>
                  <th className="pb-3 pr-4 font-medium">Side</th>
                  <th className="pb-3 pr-4 font-medium">PnL</th>
                  <th className="pb-3 pr-4 font-medium">Exit</th>
                </tr>
              </thead>
              <tbody>
                {topTradeRows.length ? (
                  topTradeRows.map((trade, index) => {
                    const pnl = Number(trade.pnl ?? 0);
                    return (
                      <tr key={`${trade.trade_id ?? trade.exit_time ?? index}`} className="border-t border-white/6">
                        <td className="py-3 pr-4 text-white">{trade.symbol}</td>
                        <td className="py-3 pr-4 text-white/65">{trade.strategy_type}</td>
                        <td className="py-3 pr-4 text-white/65">{trade.side}</td>
                        <td className={clsx("py-3 pr-4 font-medium", pnl >= 0 ? "text-emerald-300" : "text-orange-300")}>
                          {formatMoney(pnl)}
                        </td>
                        <td className="py-3 pr-4 text-white/45">{trade.exit_reason || "n/a"}</td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-white/50">
                      No closed trades yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Sleeve Leaderboard" eyebrow="Pnl by routed role" accent="green">
          <div className="grid gap-3">
            {strategyCards.length ? (
              strategyCards.map((row) => (
                <div key={row.name} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.22em] text-white/45">{row.name}</div>
                      <div className="mt-1 text-lg font-semibold text-white">{formatMoney(row.total_pnl)}</div>
                    </div>
                    <div className="text-right text-sm text-white/55">
                      <div>{row.count} trades</div>
                      <div>R {number(row.total_R, 2)}</div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-white/55">No sleeve stats yet.</div>
            )}
          </div>
        </SectionCard>
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_1fr]">
        <SectionCard title="Signal Ladder" eyebrow="Recent candidates" accent="orange">
          <div className="space-y-2">
            {topSignalRows.length ? (
              topSignalRows.slice(0, 12).map((signal, index) => (
                <div
                  key={`${signal.timestamp ?? index}-${signal.symbol ?? "signal"}`}
                  className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-white">{signal.symbol}</div>
                      <div className="text-xs uppercase tracking-[0.18em] text-white/45">
                        {signal.strategy_type} / {signal.side}
                      </div>
                    </div>
                    <div className="text-sm text-cyan-200">{number(signal.selection_score, 3)}</div>
                  </div>
                  <div className="mt-2 text-xs text-white/55">{signal.selection_reason}</div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-white/55">No signal ladder yet.</div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Current Book Context" eyebrow="What the live paper engine exposes" accent="cyan">
          <div className="grid gap-4 md:grid-cols-2">
            <StatPill label="Open positions" value={String(portfolio.open_positions ?? 0)} />
            <StatPill label="Closed trades today" value={String(portfolio.daily_closed_trades ?? 0)} />
            <StatPill label="Loss streak" value={String(portfolio.daily_loss_streak ?? 0)} tone={(portfolio.daily_loss_streak ?? 0) > 1 ? "warning" : "good"} />
            <StatPill label="Current threshold" value={number(portfolio.current_threshold, 2)} />
          </div>
          <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-6 text-white/60">
            The live paper engine currently exposes full portfolio state, sleeve economics, and tape output.
            If you want true institutional open-position blotters next, the next backend step is to publish
            per-position detail rows directly into the telemetry snapshot.
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Trade Frequency & PnL" eyebrow="Trading activity KPIs" accent="green">
        <TradeFrequencyPnlPanel
          payload={snapshot?.trade_frequency_pnl}
          title="Trade Frequency & PnL"
          subtitle="Daily / weekly / monthly / yearly realized trade telemetry"
        />
      </SectionCard>
    </div>
  );

  const allocatorContent = (
    <div className="grid gap-5">
      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <SectionCard title="Cap Pressure" eyebrow="Allocator friction" accent="orange">
          <div className="grid grid-cols-2 gap-3">
            <MetricCard
              icon={<Radar className="h-4 w-4" />}
              label="Opened"
              value={String(cumulativeCapPressure.opened_count ?? 0)}
              subtext={`share ${number(cumulativeCapPressure.opened_share ?? 0, 3)}`}
              tone="green"
            />
            <MetricCard
              icon={<Waves className="h-4 w-4" />}
              label="Cap blocked"
              value={String(cumulativeCapPressure.cap_blocked_count ?? 0)}
              subtext={`rate ${formatPct(cumulativeCapPressure.cap_block_rate ?? 0, 1)}`}
              tone="orange"
            />
          </div>
          <div className="mt-4 space-y-2">
            {(recentSelectionRows.length ? recentSelectionRows : selectionRows).slice(0, 8).map((row) => (
              <div key={String(row.selection_reason)} className="flex items-center gap-3">
                <div className="w-36 shrink-0 text-sm text-white/60">{row.selection_reason}</div>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/5">
                  <div
                    className={clsx(
                      "h-full rounded-full",
                      String(row.is_cap_pressure).toLowerCase() === "true"
                        ? "bg-gradient-to-r from-orange-400 to-orange-600"
                        : "bg-gradient-to-r from-cyan-400 to-cyan-600",
                    )}
                    style={{ width: `${Math.min(100, Number(row.share_of_decisions ?? 0) * 100)}%` }}
                  />
                </div>
                <div className="w-16 text-right text-sm text-white/75">{row.count}</div>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="Allocator Reason Matrix" eyebrow="Per-sleeve suppression map" accent="orange">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-white/45">
                <tr>
                  <th className="pb-3 pr-4 font-medium">Strategy</th>
                  <th className="pb-3 pr-4 font-medium">Reason</th>
                  <th className="pb-3 pr-4 font-medium">Count</th>
                  <th className="pb-3 pr-4 font-medium">Share</th>
                </tr>
              </thead>
              <tbody>
                {strategySelectionRows.length ? (
                  strategySelectionRows.slice(0, 18).map((row, index) => (
                    <tr key={`${row.strategy_type}-${row.selection_reason}-${index}`} className="border-t border-white/6">
                      <td className="py-3 pr-4 text-white">{row.strategy_type}</td>
                      <td className="py-3 pr-4 text-white/65">{row.selection_reason}</td>
                      <td className="py-3 pr-4 text-white/75">{row.count}</td>
                      <td className="py-3 pr-4 text-white/45">{number(row.share_of_strategy_decisions, 3)}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} className="py-6 text-center text-sm text-white/50">
                      No allocator reason matrix rows yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Allocator Decision Tape" eyebrow="Raw recent route decisions" accent="cyan">
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-sm">
            <thead className="text-white/45">
              <tr>
                <th className="pb-3 pr-4 font-medium">Time</th>
                <th className="pb-3 pr-4 font-medium">Symbol</th>
                <th className="pb-3 pr-4 font-medium">Sleeve</th>
                <th className="pb-3 pr-4 font-medium">Side</th>
                <th className="pb-3 pr-4 font-medium">Score</th>
                <th className="pb-3 pr-4 font-medium">Threshold</th>
                <th className="pb-3 pr-4 font-medium">Verdict</th>
                <th className="pb-3 pr-4 font-medium">Opened</th>
              </tr>
            </thead>
            <tbody>
              {recentAllocatorTapeRows.length ? (
                recentAllocatorTapeRows.map((row, index) => (
                  <tr key={`${row.timestamp}-${row.symbol}-${row.strategy_type}-${index}`} className="border-t border-white/6">
                    <td className="py-3 pr-4 text-white/60">{formatFlexibleTime(row.timestamp)}</td>
                    <td className="py-3 pr-4 font-semibold text-white">{row.symbol}</td>
                    <td className="py-3 pr-4 text-white/65">{row.strategy_type}</td>
                    <td className="py-3 pr-4 text-white/65">{row.side}</td>
                    <td className="py-3 pr-4 text-cyan-200">{number(row.selection_score ?? row.score ?? 0, 3)}</td>
                    <td className="py-3 pr-4 text-white/55">{number(row.threshold, 2)}</td>
                    <td className="py-3 pr-4 text-white/70">{row.final_reason ?? row.initial_reason ?? "n/a"}</td>
                    <td className="py-3 pr-4">
                      <span
                        className={clsx(
                          "rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.18em]",
                          String(row.opened).toLowerCase() === "true"
                            ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                            : "border-white/10 bg-white/5 text-white/50",
                        )}
                      >
                        {String(row.opened).toLowerCase() === "true" ? "yes" : "no"}
                      </span>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-sm text-white/50">
                    No allocator decision tape rows yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Allocator Context" eyebrow="Shared versus sleeve pressure" accent="cyan">
        <div className="grid gap-4 md:grid-cols-3">
          <StatPill label="Shared cap count" value={String(cumulativeCapPressure.shared_risk_cap_count ?? 0)} />
          <StatPill label="Sleeve cap count" value={String(cumulativeCapPressure.strategy_sleeve_cap_count ?? 0)} />
          <StatPill label="Allocator zero-risk count" value={String(cumulativeCapPressure.allocator_zero_risk_count ?? 0)} />
        </div>
      </SectionCard>
    </div>
  );

  const runtimeContent = (
    <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
      <div className="grid gap-5">
        <SectionCard title="Engine Heartbeat" eyebrow="Cycle-by-cycle liveness" accent="cyan">
          <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="grid gap-3 sm:grid-cols-2">
              <StatPill
                label="Cycle state"
                value={String(engineHeartbeat.status ?? "waiting")}
                tone={String(engineHeartbeat.status ?? "").includes("routed") ? "good" : "neutral"}
              />
              <StatPill label="Cycle duration" value={`${number(engineHeartbeat.cycle_duration_seconds, 2)}s`} />
              <StatPill label="Latest 1m timestamp" value={formatFlexibleTime(engineHeartbeat.latest_recent_1m_timestamp)} />
              <StatPill label="New 15m symbols" value={String(engineHeartbeat.new_15m_symbol_count ?? 0)} />
            </div>
            <div className="grid gap-3">
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.24em] text-white/45">Engine throughput</div>
                <MiniLineChart points={ingestionPoints} tone="cyan" className="h-[120px]" />
              </div>
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.24em] text-white/45">Opened flow</div>
                <MiniLineChart points={openFlowPoints} tone="green" className="h-[120px]" />
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Runtime Policy" eyebrow="Guard health" accent="orange">
          <div className="space-y-3">
            {runtimeRows.length ? (
              runtimeRows.map((row) => (
                <div key={String(row.strategy_type)} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-white/50">{row.strategy_type}</p>
                      <h3 className="mt-1 text-xl font-semibold">{row.label}</h3>
                    </div>
                    <div
                      className={clsx(
                        "rounded-full border px-3 py-1 text-xs",
                        String(row.fallback_to_short_only).toLowerCase() === "true"
                          ? "border-orange-400/20 bg-orange-400/10 text-orange-200"
                          : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
                      )}
                    >
                      fallback {String(row.fallback_to_short_only)}
                    </div>
                  </div>
                  <div className="mt-4 grid grid-cols-3 gap-3 text-sm text-white/70">
                    <div>
                      <div className="text-white/45">count</div>
                      <div className="mt-1 text-white">{row.count}</div>
                    </div>
                    <div>
                      <div className="text-white/45">PF</div>
                      <div className="mt-1 text-white">{number(row.profit_factor, 2)}</div>
                    </div>
                    <div>
                      <div className="text-white/45">avg R</div>
                      <div className="mt-1 text-white">{number(row.avg_R, 3)}</div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No runtime policy rows yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Validation Readiness" eyebrow="Authoritative gate and readiness truth" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Classification"
              value={String(readiness.classification ?? "unknown")}
              tone={truthy(readiness.real_money_allowed) ? "good" : "warning"}
            />
            <StatPill
              label="Validation status"
              value={String(validationTruth.validation_status ?? "unknown")}
              tone={String(validationTruth.validation_status ?? "").toLowerCase() === "complete" ? "good" : "warning"}
            />
            <StatPill
              label="Paper allowed"
              value={String(readiness.paper_runtime_allowed ?? "unknown")}
              tone={truthy(readiness.paper_runtime_allowed) ? "good" : "warning"}
            />
            <StatPill
              label="Real-money allowed"
              value={String(readiness.real_money_allowed ?? "unknown")}
              tone={truthy(readiness.real_money_allowed) ? "good" : "warning"}
            />
            <StatPill
              label="SSL verify"
              value={String(readiness?.tls?.ssl_verify ?? "unknown")}
              tone={truthy(readiness?.tls?.ssl_verify) ? "good" : "warning"}
            />
            <StatPill
              label="Full-history verdict"
              value={String(validationTruth.full_history_verdict ?? "unknown")}
              tone={verdictTone(validationTruth.full_history_verdict)}
            />
            <StatPill
              label="Holdout verdict"
              value={String(validationTruth.trailing_holdout_verdict ?? "unknown")}
              tone={verdictTone(validationTruth.trailing_holdout_verdict)}
            />
            <StatPill
              label="Holdout edge"
              value={truthy(validationTruth.holdout_is_thin) ? "thin" : "healthy"}
              tone={truthy(validationTruth.holdout_is_thin) ? "warning" : "good"}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Current runtime blockers</div>
              <div className="mt-2 text-sm text-white/75">
                {readinessBlockers.length ? readinessBlockers.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Current runtime warnings</div>
              <div className="mt-2 text-sm text-white/75">
                {readinessWarnings.length ? readinessWarnings.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Gate artifact blockers</div>
              <div className="mt-2 text-sm text-white/75">
                {gateArtifactBlockers.length ? gateArtifactBlockers.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Operator-safe warnings</div>
              <div className="mt-2 text-sm text-white/75">
                {operatorWarnings.length ? operatorWarnings.join(" / ") : "none"}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Boundary Truth" eyebrow="Validated boundary, runtime boundary, and heartbeat state" accent="cyan">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Validated boundary"
              value={formatFlexibleTime(runtimeContext.validation_boundary ?? readiness.validated_boundary)}
            />
            <StatPill label="Gate latest data" value={formatFlexibleTime(latestDataTimestamp)} />
            <StatPill label="Runtime started" value={formatFlexibleTime(soakStatus.runtime_started_at ?? runtimeContext.runtime_start_timestamp)} />
            <StatPill label="Last processed" value={formatFlexibleTime(runtimeLastProcessedTimestamp)} />
            <StatPill
              label="Heartbeat"
              value={formatFlexibleTime(soakStatus.last_heartbeat_timestamp ?? engineHeartbeat.last_heartbeat_timestamp)}
              tone={staleRuntimeDetected ? "warning" : "good"}
            />
            <StatPill
              label="Stale runtime"
              value={staleRuntimeDetected ? "true" : "false"}
              tone={staleRuntimeDetected ? "warning" : "good"}
            />
            <StatPill label="Stream status" value={connectionLabel} tone={socketConnected ? "good" : "warning"} />
            <StatPill label="Run last write" value={formatRunTime(snapshot?.run?.last_write_time)} />
          </div>
        </SectionCard>

        <SectionCard title="Runtime Mode" eyebrow="Paper-only runtime state and restore truth" accent="orange">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill label="Current mode" value={currentMode} />
            <StatPill
              label="Paper-only"
              value={String(readiness.classification === "paper-only")}
              tone={readiness.classification === "paper-only" ? "good" : "warning"}
            />
            <StatPill
              label="Real-money blocked"
              value={String(!(soakStatus.real_money_allowed ?? readiness.real_money_allowed))}
              tone={truthy(soakStatus.real_money_allowed ?? readiness.real_money_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Restored state"
              value={truthy(soakStatus.restored_state_used ?? runtimeContext.restored_from_live_state) ? "true" : "false"}
              tone={truthy(soakStatus.restored_state_used ?? runtimeContext.restored_from_live_state) ? "good" : "neutral"}
            />
            <StatPill label="Restored positions" value={String(soakStatus.restored_positions_count ?? runtimeContext.restored_position_count ?? 0)} />
            <StatPill label="Open positions" value={String(soakStatus.open_positions_count ?? portfolio.open_positions ?? 0)} />
            <StatPill
              label="Last packet"
              value={lastPacketTimestamp ? formatRunTime(lastPacketTimestamp / 1000) : "waiting"}
            />
            <StatPill label="Latest trade PnL" value={formatMoney(latestTradePnl)} tone={latestTradePnl >= 0 ? "good" : "warning"} />
          </div>
        </SectionCard>

        <SectionCard title="Sleeve Truth" eyebrow="Active and disabled sleeves, overrides, and route guards" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill label="Active sleeves" value={String(activeSleeves.length)} tone={activeSleeves.length ? "good" : "warning"} />
            <StatPill label="Disabled sleeves" value={String(disabledSleeves.length)} tone={disabledSleeves.length ? "good" : "warning"} />
            <StatPill
              label="1H short override"
              value={String(h1ShortOverrideActive)}
              tone={h1ShortOverrideActive ? "good" : "warning"}
            />
            <StatPill
              label="6H routes disabled"
              value={String(h6StandardDisabled && h6MoonshotDisabled)}
              tone={h6StandardDisabled && h6MoonshotDisabled ? "good" : "warning"}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Active sleeves</div>
              <div className="mt-2 text-sm text-white/75">
                {activeSleeves.length ? activeSleeves.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Disabled sleeves</div>
              <div className="mt-2 text-sm text-white/75">
                {disabledSleeves.length ? disabledSleeves.join(" / ") : "none"}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Paper Performance" eyebrow="Forward-paper soak metrics and runtime economics" accent="cyan">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Soak status"
              value={String(soakStatus.classification ?? readiness.classification ?? "unknown")}
              tone={truthy(soakStatus.paper_runtime_allowed ?? readiness.paper_runtime_allowed) ? "good" : "warning"}
            />
            <StatPill label="Started at" value={formatFlexibleTime(soakStatus.runtime_started_at)} />
            <StatPill label="Uptime" value={`${number(soakStatus.runtime_uptime_seconds ?? 0, 0)}s`} />
            <StatPill
              label="Paper equity"
              value={formatMoney(Number(soakStatus.current_paper_equity ?? portfolio.equity ?? 0))}
              tone="good"
            />
            <StatPill
              label="Realized since start"
              value={formatMoney(Number(soakStatus.realized_paper_pnl_since_runtime_start ?? 0))}
              tone={Number(soakStatus.realized_paper_pnl_since_runtime_start ?? 0) >= 0 ? "good" : "warning"}
            />
            <StatPill
              label="Unrealized PnL"
              value={formatMoney(Number(soakStatus.unrealized_paper_pnl ?? 0))}
              tone={Number(soakStatus.unrealized_paper_pnl ?? 0) >= 0 ? "good" : "warning"}
            />
            <StatPill label="Daily entries" value={String(soakStatus.daily_entries ?? portfolio.daily_entries_taken ?? 0)} />
            <StatPill label="Daily closed trades" value={String(soakStatus.daily_closed_trades ?? portfolio.daily_closed_trades ?? 0)} />
            <StatPill
              label="Daily closed PnL"
              value={formatMoney(Number(soakStatus.daily_closed_pnl ?? portfolio.daily_closed_pnl ?? 0))}
              tone={Number(soakStatus.daily_closed_pnl ?? portfolio.daily_closed_pnl ?? 0) >= 0 ? "good" : "warning"}
            />
          </div>
          <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Soak warnings</div>
            <div className="mt-2 text-sm text-white/75">
              {soakWarnings.length ? soakWarnings.join(" / ") : "none"}
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Daily Paper Soak Report" eyebrow="Operator evidence summary from the current soak period" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill label="Soak status" value={String(dailySoakReport.classification ?? readiness.classification ?? "unknown")} tone={truthy(dailySoakReport.paper_runtime_allowed ?? readiness.paper_runtime_allowed) ? "good" : "warning"} />
            <StatPill label="Report timestamp" value={formatFlexibleTime(dailySoakReport.report_generated_at_utc)} />
            <StatPill label="Paper equity" value={formatMoney(Number(dailySoakReport.current_paper_equity ?? soakStatus.current_paper_equity ?? portfolio.equity ?? 0))} tone="good" />
            <StatPill label="Daily PnL" value={formatMoney(Number(dailySoakReport.daily_pnl ?? soakStatus.daily_closed_pnl ?? 0))} tone={Number(dailySoakReport.daily_pnl ?? soakStatus.daily_closed_pnl ?? 0) >= 0 ? "good" : "warning"} />
            <StatPill label="Open positions" value={String(dailySoakReport.open_positions ?? soakStatus.open_positions_count ?? portfolio.open_positions ?? 0)} />
            <StatPill label="Heartbeat" value={String(dailySoakReport.heartbeat_status ?? "unknown")} tone={String(dailySoakReport.heartbeat_status ?? "").toLowerCase() === "healthy" ? "good" : "warning"} />
            <StatPill label="Promotion status" value={promotionStatus} tone="warning" />
            <StatPill label="Real-money allowed" value={String(dailySoakReport.real_money_allowed ?? readiness.real_money_allowed ?? false)} tone={truthy(dailySoakReport.real_money_allowed ?? readiness.real_money_allowed) ? "warning" : "good"} />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Active sleeves</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(dailySoakReport.active_sleeves) && dailySoakReport.active_sleeves.length
                  ? dailySoakReport.active_sleeves.join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Disabled sleeves</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(dailySoakReport.disabled_sleeves) && dailySoakReport.disabled_sleeves.length
                  ? dailySoakReport.disabled_sleeves.join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 md:col-span-2">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Warnings</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(dailySoakReport.warning_list) && dailySoakReport.warning_list.length
                  ? dailySoakReport.warning_list.join(" / ")
                  : "none"}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Paper Soak Review" eyebrow="Multi-day forward-paper evidence evaluator" accent="cyan">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill label="Review status" value={String(soakReview.soak_review_status ?? "missing")} tone={String(soakReview.soak_review_status ?? "").includes("insufficient") ? "warning" : "good"} />
            <StatPill label="Soak days" value={`${number(soakReview.soak_days_completed ?? 0, 2)} / ${String(soakReview.required_soak_days ?? "n/a")}`} />
            <StatPill label="Heartbeat" value={String(soakReview.heartbeat_health ?? "unknown")} tone={String(soakReview.heartbeat_health ?? "").toLowerCase() === "healthy" ? "good" : "warning"} />
            <StatPill label="Restart count" value={String(soakReview.restart_count ?? 0)} />
            <StatPill label="Successful restores" value={String(soakReview.successful_restore_count ?? 0)} />
            <StatPill label="Real-money allowed" value={String(soakReview.real_money_allowed ?? readiness.real_money_allowed ?? false)} tone={truthy(soakReview.real_money_allowed ?? readiness.real_money_allowed) ? "warning" : "good"} />
            <StatPill label="Paper equity" value={formatMoney(Number(soakReview.current_paper_equity ?? 0))} tone="good" />
            <StatPill label="Max drawdown" value={soakReview.max_paper_drawdown_fraction != null ? formatPct(soakReview.max_paper_drawdown_fraction, 2) : "n/a"} tone={Number(soakReview.max_paper_drawdown_fraction ?? 0) > 0.1 ? "warning" : "good"} />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Contamination check</div>
              <div className="mt-2 text-sm text-white/75">
                {soakReview.state_contamination_check?.passed ? "clean live-paper restore path only" : "review required"}
              </div>
              <div className="mt-2 break-all text-xs text-white/45">
                {String(soakReview.state_contamination_check?.restored_state_path ?? "no restored state path")}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Active / disabled sleeves</div>
              <div className="mt-2 text-sm text-white/75">
                active {Array.isArray(soakReview.active_sleeves) && soakReview.active_sleeves.length ? soakReview.active_sleeves.join(" / ") : "none"}
              </div>
              <div className="mt-1 text-sm text-white/55">
                disabled {Array.isArray(soakReview.disabled_sleeves) && soakReview.disabled_sleeves.length ? soakReview.disabled_sleeves.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">PnL evidence</div>
              <div className="mt-2 text-sm text-white/75">
                realized {formatMoney(Number(soakReview.realized_pnl_since_paper_start ?? 0))} / unrealized {formatMoney(Number(soakReview.unrealized_pnl ?? 0))}
              </div>
              <div className="mt-1 text-sm text-white/55">
                daily avg {soakReview.daily_pnl_summary?.avg != null ? formatMoney(Number(soakReview.daily_pnl_summary.avg)) : "n/a"} / median {soakReview.daily_pnl_summary?.median != null ? formatMoney(Number(soakReview.daily_pnl_summary.median)) : "n/a"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Warnings</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(soakReview.warning_list) && soakReview.warning_list.length ? soakReview.warning_list.join(" / ") : "none"}
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            {soakReviewRows.length ? (
              soakReviewRows.map((row) => (
                <div key={row.key} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{row.key}</div>
                      <div className="mt-1 text-sm text-white/75">
                        {Object.entries(row)
                          .filter(([key]) => !["key", "status"].includes(key))
                          .slice(0, 3)
                          .map(([key, value]) => `${key}:${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
                          .join(" / ") || "criterion evidence available"}
                      </div>
                    </div>
                    <div
                      className={clsx(
                        "inline-flex rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.18em]",
                        verdictTone(row.status) === "good"
                          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                          : verdictTone(row.status) === "warning"
                            ? "border-orange-400/20 bg-orange-400/10 text-orange-200"
                            : "border-white/15 bg-white/5 text-white/55",
                      )}
                    >
                      {String(row.status ?? "unknown")}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No paper soak review artifact has been published yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Baseline Freeze" eyebrow="Governance-only baseline snapshot for manual promotion review" accent="orange">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill label="Freeze timestamp" value={formatFlexibleTime(baselineFreezeSnapshot.generated_at_utc)} />
            <StatPill label="Manual review status" value={String(baselineFreezeSnapshot.manual_review_status ?? "missing")} tone={String(baselineFreezeSnapshot.manual_review_status ?? "").toLowerCase() === "no_go" ? "warning" : "good"} />
            <StatPill label="Current outcome" value={String(baselineManualReview.manual_review_outcome ?? "continue_paper_soak")} tone={String(baselineManualReview.manual_review_outcome ?? "").includes("failed") ? "warning" : "neutral"} />
            <StatPill label="Min soak days" value={String(baselineFreezeSnapshot.minimum_soak_days ?? soakReview.required_soak_days ?? "n/a")} />
            <StatPill label="Current soak days" value={number(baselineFreezeSnapshot.current_soak_days ?? soakReview.soak_days_completed ?? 0, 2)} />
            <StatPill label="Real-money allowed" value={String(baselineFreezeSnapshot.real_money_allowed ?? readiness.real_money_allowed ?? false)} tone={truthy(baselineFreezeSnapshot.real_money_allowed ?? readiness.real_money_allowed) ? "warning" : "good"} />
            <StatPill label="SSL verify" value={String(baselineFreezeSnapshot.ssl_verify ?? readiness.tls?.ssl_verify ?? false)} tone={truthy(baselineFreezeSnapshot.ssl_verify ?? readiness.tls?.ssl_verify) ? "good" : "warning"} />
            <StatPill label="Git commit" value={String(baselineFreezeSnapshot.git_commit ?? "unknown")} />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Allowed review outcomes</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(baselineManualReview.allowed_manual_review_outcomes) && baselineManualReview.allowed_manual_review_outcomes.length
                  ? baselineManualReview.allowed_manual_review_outcomes.join(" / ")
                  : "continue_paper_soak / paper_soak_failed / eligible_for_capital_refactor_research / eligible_for_tiny_live_pilot_later"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Manual review rationale</div>
              <div className="mt-2 text-sm text-white/75">
                {String(baselineManualReview.rationale ?? "No baseline freeze snapshot published yet.")}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Capital Refactor Scaffold" eyebrow="Dormant research inventory only, with zero execution authority" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Root enabled"
              value={String(capitalRefactorScaffold.capital_refactor_enabled ?? false)}
              tone={truthy(capitalRefactorScaffold.capital_refactor_enabled) ? "warning" : "good"}
            />
            <StatPill
              label="Behavior change allowed"
              value={String(capitalRefactorScaffold.behavior_change_allowed ?? false)}
              tone={truthy(capitalRefactorScaffold.behavior_change_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Real-money allowed"
              value={String(capitalRefactorScaffold.real_money_allowed ?? false)}
              tone={truthy(capitalRefactorScaffold.real_money_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Promotion review"
              value={String(capitalRefactorScaffold.promotion_review?.status ?? "missing")}
              tone={String(capitalRefactorScaffold.promotion_review?.status ?? "").toLowerCase() === "scaffold_only" ? "good" : "warning"}
            />
            <StatPill label="Validated boundary" value={formatFlexibleTime(capitalRefactorScaffold.validated_boundary)} />
            <StatPill
              label="SSL verify"
              value={String(capitalRefactorScaffold.ssl_verify ?? readiness?.tls?.ssl_verify ?? false)}
              tone={truthy(capitalRefactorScaffold.ssl_verify ?? readiness?.tls?.ssl_verify) ? "good" : "warning"}
            />
            <StatPill label="Modules present" value={String(capitalRefactorModulesPresent)} tone={capitalRefactorModulesPresent ? "good" : "warning"} />
            <StatPill label="Generated at" value={formatFlexibleTime(capitalRefactorScaffold.generated_at_utc)} />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Scaffold warning</div>
              <div className="mt-2 text-sm text-white/75">
                {String(capitalRefactorScaffold.warning ?? "no scaffold artifact published")}
              </div>
              <div className="mt-2 break-all text-xs text-white/45">
                {String(capitalRefactorScaffold.config_path ?? "no config path")}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Default capital lanes</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(capitalRefactorScaffold.default_capital_lanes) && capitalRefactorScaffold.default_capital_lanes.length
                  ? capitalRefactorScaffold.default_capital_lanes
                      .map((lane: Row) => `${lane.name}:${lane.priority ?? "n/a"}`)
                      .join(" / ")
                  : "none"}
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            {capitalRefactorLayers.length ? (
              capitalRefactorLayers.map((row) => (
                <div key={row.key} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                  <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{row.key}</div>
                      <div className="mt-1 text-sm text-white/75">
                        present {String(row.present)} / enabled {String(row.enabled)} / behavior change {String(row.behavior_change_allowed)}
                      </div>
                    </div>
                    <div
                      className={clsx(
                        "inline-flex rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.18em]",
                        truthy(row.enabled) || truthy(row.behavior_change_allowed)
                          ? "border-orange-400/20 bg-orange-400/10 text-orange-200"
                          : "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
                      )}
                    >
                      {truthy(row.enabled) || truthy(row.behavior_change_allowed) ? "guard review required" : "dormant"}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No capital scaffold inventory artifact has been published yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Future Market Structure Scaffold" eyebrow="Support/resistance and liquidity research only, fully disabled" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Enabled"
              value={String(marketStructureScaffold.enabled ?? false)}
              tone={truthy(marketStructureScaffold.enabled) ? "warning" : "good"}
            />
            <StatPill
              label="Display only"
              value={String(marketStructureScaffold.display_only ?? false)}
              tone={truthy(marketStructureScaffold.display_only) ? "good" : "warning"}
            />
            <StatPill
              label="Behavior change allowed"
              value={String(marketStructureScaffold.behavior_change_allowed ?? false)}
              tone={truthy(marketStructureScaffold.behavior_change_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Future research only"
              value={String(marketStructureScaffold.future_research_only ?? false)}
              tone={truthy(marketStructureScaffold.future_research_only) ? "good" : "warning"}
            />
            <StatPill
              label="Real-money allowed"
              value={String(marketStructureScaffold.real_money_allowed ?? false)}
              tone={truthy(marketStructureScaffold.real_money_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Modules present"
              value={String(marketStructureModulesPresent)}
              tone={marketStructureModulesPresent ? "good" : "warning"}
            />
            <StatPill label="Scaffold" value={String(marketStructureScaffold.scaffold ?? "missing")} />
            <StatPill label="Generated at" value={formatFlexibleTime(marketStructureScaffold.generated_at_utc)} />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Warning</div>
              <div className="mt-2 text-sm text-white/75">
                {String(marketStructureScaffold.warning ?? "no market structure scaffold artifact published")}
              </div>
              <div className="mt-2 break-all text-xs text-white/45">
                {String(marketStructureScaffold.config_path ?? "no config path")}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Scope</div>
              <div className="mt-2 text-sm text-white/75">
                Support/resistance zones, liquidity pools, sweeps, failed breaks, retests, and HTF context remain visualization and diagnostics scaffolding only.
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Capital Diagnostics" eyebrow="Phase 1 evidence only, with no runtime authority" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Phase"
              value={String(capitalRefactorDiagnostics.phase ?? "missing")}
              tone={String(capitalRefactorDiagnostics.phase ?? "") === "phase_1_diagnostics_only" ? "good" : "warning"}
            />
            <StatPill
              label="Diagnostics only"
              value={String(capitalRefactorDiagnostics.diagnostics_only ?? false)}
              tone={truthy(capitalRefactorDiagnostics.diagnostics_only) ? "good" : "warning"}
            />
            <StatPill
              label="Behavior change allowed"
              value={String(capitalRefactorDiagnostics.behavior_change_allowed ?? false)}
              tone={truthy(capitalRefactorDiagnostics.behavior_change_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Real-money allowed"
              value={String(capitalRefactorDiagnostics.real_money_allowed ?? false)}
              tone={truthy(capitalRefactorDiagnostics.real_money_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Allocator behavior changed"
              value={String(capitalRefactorDiagnostics.allocator_behavior_changed ?? false)}
              tone={truthy(capitalRefactorDiagnostics.allocator_behavior_changed) ? "warning" : "good"}
            />
            <StatPill
              label="Risk behavior changed"
              value={String(capitalRefactorDiagnostics.risk_behavior_changed ?? false)}
              tone={truthy(capitalRefactorDiagnostics.risk_behavior_changed) ? "warning" : "good"}
            />
            <StatPill
              label="Sizing behavior changed"
              value={String(capitalRefactorDiagnostics.sizing_behavior_changed ?? false)}
              tone={truthy(capitalRefactorDiagnostics.sizing_behavior_changed) ? "warning" : "good"}
            />
            <StatPill
              label="Generated at"
              value={formatFlexibleTime(capitalRefactorDiagnostics.generated_at_utc)}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Phase 1 warnings</div>
              <div className="mt-2 text-sm text-white/75">
                {capitalDiagnosticsWarnings.length ? capitalDiagnosticsWarnings.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Diagnostics reports</div>
              <div className="mt-2 text-sm text-white/75">
                {capitalDiagnosticsReports.length
                  ? capitalDiagnosticsReports.map((row) => `${row.key}:${row.status ?? "unknown"}`).join(" / ")
                  : "none"}
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {capitalDiagnosticsReports.length ? (
              capitalDiagnosticsReports.map((artifact) => (
                <div key={artifact.key} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{artifact.key}</div>
                      <div className="mt-2 break-all text-sm text-white/75">{artifact.path ?? "unknown path"}</div>
                    </div>
                    <div
                      className={clsx(
                        "inline-flex rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.18em]",
                        artifact.status === "healthy"
                          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                          : "border-orange-400/20 bg-orange-400/10 text-orange-200",
                      )}
                    >
                      {artifact.status ?? "unknown"}
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-3 text-sm text-white/65">
                    <div>exists {String(artifact.exists)}</div>
                    <div>last modified {formatFlexibleTime(artifact.last_modified_timestamp)}</div>
                    <div>age {artifact.age_seconds != null ? `${number(artifact.age_seconds, 0)}s` : "n/a"}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No Phase 1 diagnostics artifact has been published yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Capital Evidence Review" eyebrow="Decision memo only, defining if Phase 2 is even justified" accent="green">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill
              label="Review phase"
              value={String(capitalRefactorEvidenceReview.phase ?? "missing")}
              tone={String(capitalRefactorEvidenceReview.phase ?? "") === "phase_1_evidence_review" ? "good" : "warning"}
            />
            <StatPill
              label="Evidence strength"
              value={String(capitalRefactorEvidenceReview.evidence_strength?.overall ?? "unknown")}
              tone={String(capitalRefactorEvidenceReview.evidence_strength?.phase2_backtest_only_justified ?? "false") === "true" ? "good" : "warning"}
            />
            <StatPill
              label="Recommended next phase"
              value={String(capitalRefactorEvidenceReview.evidence_strength?.recommended_next_phase ?? "none")}
              tone="good"
            />
            <StatPill
              label="Behavior change allowed"
              value={String(capitalRefactorEvidenceReview.behavior_change_allowed ?? false)}
              tone={truthy(capitalRefactorEvidenceReview.behavior_change_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="Real-money allowed"
              value={String(capitalRefactorEvidenceReview.real_money_allowed ?? false)}
              tone={truthy(capitalRefactorEvidenceReview.real_money_allowed) ? "warning" : "good"}
            />
            <StatPill
              label="6H enabled"
              value={String(capitalRefactorEvidenceReview.six_h_enabled ?? false)}
              tone={truthy(capitalRefactorEvidenceReview.six_h_enabled) ? "warning" : "good"}
            />
            <StatPill
              label="1H short override"
              value={String(capitalRefactorEvidenceReview.h1_short_override_active ?? false)}
              tone={truthy(capitalRefactorEvidenceReview.h1_short_override_active) ? "good" : "warning"}
            />
            <StatPill
              label="Generated at"
              value={formatFlexibleTime(capitalRefactorEvidenceReview.generated_at_utc)}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Top rejection reasons</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(capitalRefactorEvidenceReview.top_rejection_reasons) && capitalRefactorEvidenceReview.top_rejection_reasons.length
                  ? capitalRefactorEvidenceReview.top_rejection_reasons
                      .slice(0, 4)
                      .map((row: Row) => `${row.rejection_reason}:${row.count}`)
                      .join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Top blocking constraints</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(capitalRefactorEvidenceReview.top_blocking_constraints) && capitalRefactorEvidenceReview.top_blocking_constraints.length
                  ? capitalRefactorEvidenceReview.top_blocking_constraints
                      .slice(0, 4)
                      .map((row: Row) => `${row.blocking_constraint}:${row.count}`)
                      .join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Review warnings</div>
              <div className="mt-2 text-sm text-white/75">
                {capitalEvidenceWarnings.length ? capitalEvidenceWarnings.join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Phase 2 no-go reasoning</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(capitalRefactorEvidenceReview.phase2_not_allowed_yet_reasoning) && capitalRefactorEvidenceReview.phase2_not_allowed_yet_reasoning.length
                  ? capitalRefactorEvidenceReview.phase2_not_allowed_yet_reasoning.slice(0, 3).join(" / ")
                  : "none"}
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {capitalEvidenceReports.length ? (
              capitalEvidenceReports.map((artifact) => (
                <div key={artifact.key} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{artifact.key}</div>
                      <div className="mt-2 break-all text-sm text-white/75">{artifact.path ?? "unknown path"}</div>
                    </div>
                    <div
                      className={clsx(
                        "inline-flex rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.18em]",
                        artifact.status === "healthy"
                          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                          : "border-orange-400/20 bg-orange-400/10 text-orange-200",
                      )}
                    >
                      {artifact.status ?? "unknown"}
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-3 text-sm text-white/65">
                    <div>exists {String(artifact.exists)}</div>
                    <div>last modified {formatFlexibleTime(artifact.last_modified_timestamp)}</div>
                    <div>age {artifact.age_seconds != null ? `${number(artifact.age_seconds, 0)}s` : "n/a"}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No Phase 1 evidence review artifact has been published yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Capital Refactor Research House" eyebrow="Candidate registry, ladder governance, and execution-cost realism" accent="orange">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatPill label="Current phase" value={String(capitalRefactorMasterPlan.current_state?.current_phase ?? capitalRefactorMasterPlan.current_phase ?? "phase3_guarded_12h_structural_relief")} />
            <StatPill label="Candidate count" value={String(capitalCandidateCount)} tone={capitalCandidateCount > 0 ? "good" : "warning"} />
            <StatPill label="Ladder stages" value={String(capitalLadderStages.length)} tone={capitalLadderStages.length > 0 ? "good" : "warning"} />
            <StatPill label="Execution cost scenarios" value={String(executionCostScenarioCount)} tone={executionCostScenarioCount > 0 ? "good" : "warning"} />
            <StatPill
              label="Auto promotion"
              value={String(capitalRefactorPromotionGovernance.auto_promotion_supported ?? false)}
              tone={truthy(capitalRefactorPromotionGovernance.auto_promotion_supported) ? "warning" : "good"}
            />
            <StatPill
              label="Manual recommendation"
              value={String(capitalRefactorPromotionGovernance.recommendation ?? "continue_research")}
              tone={String(capitalRefactorPromotionGovernance.recommendation ?? "").toLowerCase().includes("reject") ? "warning" : "neutral"}
            />
            <StatPill
              label="Execution realism"
              value={String(capitalRefactorExecutionRealism.research_only ?? true)}
              tone={truthy(capitalRefactorExecutionRealism.research_only ?? true) ? "good" : "warning"}
            />
            <StatPill
              label="Real-money allowed"
              value={String(capitalRefactorPromotionGovernance.safety_flags?.real_money_allowed ?? false)}
              tone={truthy(capitalRefactorPromotionGovernance.safety_flags?.real_money_allowed) ? "warning" : "good"}
            />
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Master layers</div>
              <div className="mt-2 text-sm text-white/75">
                {capitalMasterLayers.length ? capitalMasterLayers.slice(0, 6).join(" / ") : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Ladder order</div>
              <div className="mt-2 text-sm text-white/75">
                {capitalLadderStages.length
                  ? capitalLadderStages.map((row: Row) => String(row.stage ?? "unknown")).join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Execution realism rule</div>
              <div className="mt-2 text-sm text-white/75">
                {String(capitalRefactorExecutionRealism.acceptance_rule ?? "No execution cost rule artifact published yet.")}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Governance</div>
              <div className="mt-2 text-sm text-white/75">
                {Array.isArray(capitalRefactorPromotionGovernance.allowed_recommendations)
                  ? capitalRefactorPromotionGovernance.allowed_recommendations.join(" / ")
                  : "continue_research / reject / inconclusive"}
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {capitalResearchReports.length ? (
              capitalResearchReports.map((artifact) => (
                <div key={artifact.key} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{artifact.key}</div>
                      <div className="mt-2 break-all text-sm text-white/75">{artifact.path ?? "unknown path"}</div>
                    </div>
                    <div
                      className={clsx(
                        "inline-flex rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.18em]",
                        artifact.status === "healthy"
                          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                          : "border-orange-400/20 bg-orange-400/10 text-orange-200",
                      )}
                    >
                      {artifact.status ?? "unknown"}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No capital refactor master artifacts have been published yet.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Artifact Freshness" eyebrow="Source-of-truth file health and modification state" accent="orange">
          <div className="space-y-3">
            {artifactRows.length ? (
              artifactRows.map((artifact) => (
                <div key={artifact.key} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">{artifact.key}</div>
                      <div className="mt-2 break-all text-sm text-white/75">{artifact.path ?? "unknown path"}</div>
                    </div>
                    <div
                      className={clsx(
                        "inline-flex rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.18em]",
                        artifact.status === "healthy"
                          ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                          : "border-orange-400/20 bg-orange-400/10 text-orange-200",
                      )}
                    >
                      {artifact.status ?? "unknown"}
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-3 text-sm text-white/65">
                    <div>exists {String(artifact.exists)}</div>
                    <div>last modified {formatFlexibleTime(artifact.last_modified_timestamp)}</div>
                    <div>age {artifact.age_seconds != null ? `${number(artifact.age_seconds, 0)}s` : "n/a"}</div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No artifact freshness rows available.
              </div>
            )}
          </div>
        </SectionCard>

        <SectionCard title="Diagnostics" eyebrow="Allocator, strategy, and last runtime event summary" accent="green">
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Allocator rejection counts</div>
              <div className="mt-2 text-sm text-white/75">
                {Object.keys(latestAllocatorRejections).length
                  ? Object.entries(latestAllocatorRejections).map(([key, value]) => `${key}:${value}`).join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Strategy trade counts</div>
              <div className="mt-2 text-sm text-white/75">
                {Object.keys(strategyTradeCounts).length
                  ? Object.entries(strategyTradeCounts).map(([key, value]) => `${key}:${value}`).join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Strategy paper PnL</div>
              <div className="mt-2 text-sm text-white/75">
                {Object.keys(strategyLevelPnl).length
                  ? Object.entries(strategyLevelPnl)
                      .map(([key, value]) => `${key}:${formatMoney(value)}`)
                      .join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Last runtime event</div>
              <div className="mt-2 text-sm text-white/75">
                {Object.keys(lastRuntimeEvent).length
                  ? [
                      `startup ${formatFlexibleTime(lastRuntimeEvent.startup_time)}`,
                      `restore ${String(lastRuntimeEvent.restore_happened)}`,
                      `positions ${String(lastRuntimeEvent.restored_positions_count ?? 0)}`,
                      `boundary ${formatFlexibleTime(lastRuntimeEvent.validation_boundary)}`,
                    ].join(" / ")
                  : "none"}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 md:col-span-2">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Gate metrics</div>
              <div className="mt-2 text-sm text-white/75">
                full-history PF {number(validationTruth.full_history_metrics?.profit_factor ?? 0, 2)} / net {formatMoney(validationTruth.full_history_metrics?.net_pnl ?? 0)} / holdout PF {number(validationTruth.trailing_holdout_metrics?.profit_factor ?? 0, 2)} / holdout net {formatMoney(validationTruth.trailing_holdout_metrics?.net_pnl ?? 0)}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 md:col-span-2">
              <div className="text-[11px] uppercase tracking-[0.22em] text-white/45">Gate status blockers</div>
              <div className="mt-2 text-sm text-white/75">
                {gateStatusBlockers.length ? gateStatusBlockers.join(" / ") : "none"}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Cycle Tape" eyebrow="Latest engine loop states" accent="orange">
          <div className="space-y-2">
            {recentCycleTapeRows.length ? (
              recentCycleTapeRows.map((row, index) => (
                <div
                  key={`${row.cycle_count ?? index}-${row.cycle_completed_at ?? row.cycle_started_at ?? "cycle"}`}
                  className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs uppercase tracking-[0.18em] text-white/45">
                        cycle {row.cycle_count}
                      </div>
                      <div className="mt-1 font-medium text-white">{row.status}</div>
                    </div>
                    <div className="text-right text-sm text-white/55">
                      <div>{number(row.cycle_duration_seconds, 2)}s</div>
                      <div>{formatFlexibleTime(row.cycle_completed_at)}</div>
                    </div>
                  </div>
                  <div className="mt-3 grid gap-2 md:grid-cols-4 text-[11px] uppercase tracking-[0.16em] text-white/55">
                    <div className="rounded-2xl border border-white/8 bg-black/10 px-3 py-2">
                      new 15m {row.new_15m_symbol_count ?? 0}
                    </div>
                    <div className="rounded-2xl border border-white/8 bg-black/10 px-3 py-2">
                      candidates {row.candidates_built ?? 0}
                    </div>
                    <div className="rounded-2xl border border-white/8 bg-black/10 px-3 py-2">
                      opened {row.opened_count ?? 0}
                    </div>
                    <div className="rounded-2xl border border-white/8 bg-black/10 px-3 py-2">
                      latest 1m {formatFlexibleTime(row.latest_recent_1m_timestamp)}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-white/55">
                No cycle tape rows yet.
              </div>
            )}
          </div>
        </SectionCard>
      </div>

      <div className="grid gap-5">
        <SectionCard title="Timeframe Synchronization" eyebrow="Per-symbol live feed and evaluation state" accent="orange">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-white/45">
                <tr>
                  <th className="pb-3 pr-4 font-medium">Symbol</th>
                  <th className="pb-3 pr-4 font-medium">1m latest</th>
                  <th className="pb-3 pr-4 font-medium">15m latest</th>
                  <th className="pb-3 pr-4 font-medium">1h latest</th>
                  <th className="pb-3 pr-4 font-medium">12h latest</th>
                  <th className="pb-3 pr-4 font-medium">New 15m</th>
                  <th className="pb-3 pr-4 font-medium">Candidates</th>
                </tr>
              </thead>
              <tbody>
                {symbolPipelineRows.length ? (
                  symbolPipelineRows.map((row) => (
                    <tr key={String(row.symbol)} className="border-t border-white/6">
                      <td className="py-3 pr-4 font-semibold text-white">{row.symbol}</td>
                      <td className="py-3 pr-4 text-white/65">{formatFlexibleTime(row.latest_recent_1m_timestamp)}</td>
                      <td className="py-3 pr-4 text-white/65">{formatFlexibleTime(row.latest_15m_timestamp)}</td>
                      <td className="py-3 pr-4 text-white/65">{formatFlexibleTime(row.latest_1h_timestamp)}</td>
                      <td className="py-3 pr-4 text-white/65">{formatFlexibleTime(row.latest_12h_timestamp)}</td>
                      <td className="py-3 pr-4">
                        <span
                          className={clsx(
                            "rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.18em]",
                            String(row.new_15m_candle).toLowerCase() === "true"
                              ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-200"
                              : "border-white/10 bg-white/5 text-white/50",
                          )}
                        >
                          {String(row.new_15m_candle).toLowerCase() === "true" ? "yes" : "no"}
                        </span>
                      </td>
                      <td className="py-3 pr-4 text-white/70">
                        {row.candidate_count} {row.candidate_strategies ? `/${row.candidate_strategies}` : ""}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-white/50">
                      No symbol pipeline rows yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard title="Operator Notes" eyebrow="How the cockpit should be read" accent="green">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="mb-2 flex items-center gap-2 text-cyan-200">
                <CandlestickChart className="h-4 w-4" />
                <span className="text-sm font-medium">Price and execution</span>
              </div>
              <p className="text-sm leading-6 text-white/60">
                Inspect local candles with pan and zoom, see trade markers on the bar stream, and read
                the latest candidate tape without leaving the run context.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="mb-2 flex items-center gap-2 text-emerald-200">
                <Shield className="h-4 w-4" />
                <span className="text-sm font-medium">Allocator pressure</span>
              </div>
              <p className="text-sm leading-6 text-white/60">
                Track whether the routed stack is healthy because the sleeve is good, or whether it is
                being starved by shared-pool caps, sleeve caps, or a guard fallback.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="mb-2 flex items-center gap-2 text-orange-200">
                <AlertTriangle className="h-4 w-4" />
                <span className="text-sm font-medium">Truthful scope</span>
              </div>
              <p className="text-sm leading-6 text-white/60">
                This cockpit is an observer layer around live-paper artifacts. It does not place trades,
                invent fills, or bypass the routed engine. It visualizes what the live stack already writes.
              </p>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );

  const currentView = {
    overview: overviewContent,
    market: marketContent,
    atlas: atlasContent,
    portfolio: portfolioContent,
    allocator: allocatorContent,
    runtime: runtimeContent,
  }[view];
  const headerExpanded = view === "overview";

  return (
    <main className="min-h-screen bg-transparent text-white">
      <header className="sticky top-0 z-50 border-b border-white/8 bg-[#040914]/88 shadow-[0_16px_44px_rgba(4,8,22,0.42)] backdrop-blur-2xl">
        <div
          className={clsx(
            "mx-auto flex max-w-[1900px] flex-col px-5 md:px-8 xl:px-10",
            headerExpanded ? "gap-4 py-4 md:py-5 xl:py-5" : "gap-3 py-3 md:py-3.5 xl:py-3.5",
          )}
        >
          <div
            className={clsx(
              "grid xl:items-center",
              headerExpanded ? "gap-5 xl:grid-cols-[280px_minmax(0,1fr)]" : "gap-3 xl:grid-cols-[92px_minmax(0,1fr)]",
            )}
          >
            <div
              className={clsx(
                "relative overflow-hidden bg-[linear-gradient(145deg,rgba(11,23,45,0.7),rgba(6,12,28,0.42)_30%,rgba(8,18,39,0.7))]",
                headerExpanded
                  ? "hidden h-[190px] rounded-[32px] shadow-[0_20px_56px_rgba(5,10,28,0.48)] xl:block"
                  : "hidden h-[72px] rounded-[20px] shadow-[0_12px_28px_rgba(5,10,28,0.28)] xl:block",
              )}
            >
              <div className="absolute inset-0 flex items-center justify-center">
                <Image
                  src="/logo-hero.png"
                  alt="Retail Trading System hero logo"
                  fill
                  className={clsx(
                    "object-contain p-0 drop-shadow-[0_0_28px_rgba(83,242,255,0.16)]",
                    headerExpanded ? "scale-[1.12]" : "scale-[0.92]",
                  )}
                  priority
                />
              </div>
            </div>

            <div className="min-w-0">
              <div className={clsx("flex flex-wrap items-center", headerExpanded ? "gap-2" : "gap-1.5")}>
                <span className="rounded-full border border-cyan-300/30 bg-cyan-400/14 px-3 py-1 text-[10px] uppercase tracking-[0.34em] text-cyan-100 shadow-[0_0_18px_rgba(83,242,255,0.12)]">
                  Retail Trading System
                </span>
                <span className={clsx("rounded-full px-3 py-1 text-[10px] uppercase tracking-[0.28em]", modeMeta.accent)}>
                  {modeMeta.shellLabel}
                </span>
                <span className="rounded-full border border-emerald-300/28 bg-emerald-400/14 px-3 py-1 text-[10px] uppercase tracking-[0.28em] text-emerald-100 shadow-[0_0_18px_rgba(52,211,153,0.12)]">
                  {viewMeta.eyebrow}
                </span>
              </div>
              <h1
                className={clsx(
                  "font-semibold tracking-[0.01em] text-white",
                  headerExpanded ? "mt-3 text-3xl md:text-[2.2rem]" : "mt-1.5 text-[1.7rem] md:text-[1.85rem]",
                )}
              >
                {headerExpanded ? "Command Deck" : viewMeta.label}
              </h1>
              <div className={clsx("flex flex-wrap", headerExpanded ? "mt-2 gap-2" : "mt-1.5 gap-1.5")}>
                {(["paper", "backtest", "live"] as DashboardMode[]).map((item) => {
                  const isActive = item === dashboardMode;
                  const meta = MODE_META[item];
                  return (
                    <Link
                      key={item}
                      href={meta.routeBase}
                      className={clsx(
                        "holo-button rounded-full border uppercase tracking-[0.18em] transition-all",
                        headerExpanded ? "px-3 py-1 text-xs" : "px-2.5 py-1 text-[10px]",
                        isActive
                          ? "border-cyan-300/28 bg-cyan-400/14 text-cyan-100 shadow-[0_0_20px_rgba(83,242,255,0.12)]"
                          : "border-white/10 bg-white/5 text-white/60 hover:border-cyan-300/18 hover:text-white",
                      )}
                    >
                      {meta.shellLabel}
                    </Link>
                  );
                })}
              </div>
              {dashboardMode === "backtest" ? (
                <>
                  <div className={clsx("flex flex-wrap", headerExpanded ? "mt-3 gap-2" : "mt-2 gap-1.5")}>
                    <span className="inline-block rounded-full border border-amber-400/20 bg-amber-400/8 px-3 py-1 text-xs uppercase tracking-[0.18em] text-amber-200">
                      BACKTEST MODE
                    </span>
                    <span className="inline-block rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-cyan-200">
                      {snapshot?.run?.run_id ? `run ${snapshot.run.run_id}` : "no run loaded"}
                    </span>
                    <span className="inline-block rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-white/65">
                      replay {formatFlexibleTime(replayTimestamp)}
                    </span>
                    <span className="inline-block rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-cyan-200">
                      progress {replayProgressPercent.toFixed(1)}%
                    </span>
                    <span className="inline-block rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-emerald-200">
                      {replayWindowPolicy}
                    </span>
                  </div>
                  {headerExpanded ? (
                    <div className="mt-3 rounded-3xl border border-amber-400/20 bg-amber-400/10 px-4 py-3 text-sm text-amber-100">
                      This is active replay state. The chart clips to the current checkpoint, while tape, KPI, and allocator panels read directly from the running Phase 2 artifact stream.
                    </div>
                  ) : null}
                </>
              ) : dashboardMode === "live" ? (
                headerExpanded ? (
                  <div className="mt-3 rounded-3xl border border-emerald-400/20 bg-emerald-400/10 px-4 py-3 text-sm text-emerald-100">
                    Live Operations is the runtime command surface. It stays wired to the active telemetry rail and is ready to front a future execution adapter without redesigning the cockpit.
                  </div>
                ) : null
              ) : null}
              <p
                className={clsx(
                  "max-w-3xl text-slate-200/72",
                  headerExpanded ? "mt-3 text-sm leading-7 md:text-[15px]" : "mt-1.5 text-[12px] leading-5",
                )}
              >
                {headerExpanded ? modeMeta.summary : `${modeMeta.shellLabel} / ${viewMeta.description}`}
              </p>

              <div className={clsx("flex flex-wrap", headerExpanded ? "mt-5 gap-2" : "mt-2 gap-1.5")}>
                {viewTabs.map((tab) => {
                  const isActive = view === tab.key;
                  return (
                    <Link
                      key={tab.key}
                      href={tab.href}
                      className={clsx(
                        "holo-button group flex items-center rounded-2xl border transition-all",
                        headerExpanded ? "gap-2 px-4 py-2 text-sm" : "gap-1.5 px-3 py-1.5 text-[12px]",
                        isActive
                          ? "border-cyan-300/36 bg-cyan-400/14 text-cyan-50 shadow-[0_0_24px_rgba(83,242,255,0.14)]"
                          : "border-slate-200/10 bg-slate-900/35 text-slate-200/72 hover:border-cyan-300/20 hover:bg-slate-800/45 hover:text-white",
                      )}
                    >
                      {tab.icon}
                      <span>{tab.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          </div>

          <div
            className={clsx(
              headerExpanded
                ? "grid gap-2 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8"
                : "flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
            )}
          >
            <HeaderMetric
              label="Connection"
              value={connectionLabel}
              subtext={formatFlexibleTime(engineHeartbeat.latest_recent_1m_timestamp || snapshot?.run?.last_write_time)}
              tone={connectionTone}
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={[
                { value: socketConnected ? 1 : 0.2 },
                { value: socketConnected ? 1 : 0.25 },
                { value: socketConnected ? 1 : 0.15 },
              ]}
              pulse
            />
            <HeaderMetric
              label="Engine"
              value={String(engineHeartbeat.status ?? "waiting")}
              subtext={`cycle ${engineHeartbeat.cycle_count ?? 0}`}
              tone={String(engineHeartbeat.status ?? "").includes("routed") ? "green" : "cyan"}
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={enginePulsePoints}
              pulse
            />
            <HeaderMetric
              label="Replay"
              value={dashboardMode === "backtest" ? `${replayProgressPercent.toFixed(1)}%` : formatFlexibleTime(replayTimestamp)}
              subtext={
                dashboardMode === "backtest"
                  ? `${replayNextIndex}${replayEstimatedBars ? ` / ${replayEstimatedBars}` : ""} bars`
                  : snapshot?.run?.run_id
                    ? `run ${snapshot.run.run_id}`
                    : "no run"
              }
              tone="orange"
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={[
                { value: Math.max(0, replayProgressPercent / 100) },
                { value: Math.max(0, replayProgressPercent / 120) },
                { value: Math.max(0, replayProgressPercent / 150) },
              ]}
            />
            <HeaderMetric
              label="Equity"
              value={formatMoney(portfolio.equity)}
              subtext={`PnL ${formatMoney(livePnl)}`}
              tone={livePnl >= 0 ? "green" : "orange"}
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={equityPoints.slice(-20)}
            />
            <HeaderMetric
              label="Guard"
              value={runtimeRow?.label ?? "n/a"}
              subtext={`PF ${number(runtimeRow?.profit_factor, 2)}`}
              tone="orange"
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={runtimePoints}
              pulse={String(runtimeRow?.fallback_to_short_only).toLowerCase() !== "true"}
            />
            <HeaderMetric
              label="Open positions"
              value={String(portfolio.open_positions ?? 0)}
              subtext={`entries ${portfolio.daily_entries_taken ?? 0}`}
              tone="cyan"
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={pnlPoints.slice(-20)}
            />
            <HeaderMetric
              label="Shared cap"
              value={String(cumulativeCapPressure.shared_risk_cap_count ?? 0)}
              subtext={`recent ${recentCapPressure.shared_risk_cap_count ?? 0}`}
              tone="cyan"
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[168px] shrink-0" : undefined}
              points={capPoints}
            />
            <HeaderMetric
              label="Top symbols"
              value={topSymbols.length ? topSymbols.join(" / ") : "idle"}
              subtext={snapshot?.run?.run_id ?? "no run"}
              tone="neutral"
              compact={!headerExpanded}
              className={!headerExpanded ? "min-w-[220px] shrink-0" : undefined}
              points={thresholdPoints.slice(-20)}
            />
          </div>

          <div className={clsx("flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between", headerExpanded ? "" : "hidden")}>
            <div className="flex items-center gap-3 rounded-2xl border border-slate-200/10 bg-slate-900/40 px-4 py-2 text-sm text-slate-200/78 shadow-[0_18px_40px_rgba(4,9,20,0.24)]">
              <Globe className="h-4 w-4 text-cyan-200" />
              <span>{viewMeta.description}</span>
            </div>

            <div className="flex items-center gap-3 rounded-2xl border border-slate-200/10 bg-slate-900/40 px-4 py-2 text-sm text-slate-200/78 shadow-[0_18px_40px_rgba(4,9,20,0.24)]">
              <Clock3 className="h-4 w-4 text-orange-200" />
              <span>
                {dashboardMode === "backtest"
                  ? snapshot?.run?.last_write_time
                    ? formatRunTime(snapshot.run.last_write_time)
                    : "awaiting data"
                  : lastPacketTimestamp
                    ? formatRunTime(lastPacketTimestamp / 1000)
                    : "awaiting stream"}
              </span>
            </div>
          </div>
        </div>
      </header>

      <div className="px-5 pb-8 pt-5 md:px-8 md:pt-6 xl:px-10 xl:pt-6">
        <div className="cinematic-card data-grid mx-auto max-w-[1900px] rounded-[34px] border border-white/8 p-4 md:p-6">
          <AnimatePresence mode="wait">
            <motion.div
              key={view}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -18 }}
              transition={{ duration: 0.26 }}
              className="min-h-[720px]"
            >
              {currentView}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </main>
  );
}
