"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import useSWR from "swr";
import clsx from "clsx";
import {
  ArrowRight,
  BarChart3,
  CandlestickChart,
  Database,
  Layers3,
  Settings2,
  ShieldAlert,
  Vault,
  Waves,
} from "lucide-react";
import { CandlePanel } from "@/components/candle-panel";
import { MiniLineChart } from "@/components/mini-line-chart";
import { TradeFrequencyPnlPanel, type TradeFrequencyPnlPayload } from "@/components/trade-frequency-pnl-panel";

type StructuralView =
  | "overview"
  | "market-replay"
  | "structure-map"
  | "profit-vault"
  | "trade-review"
  | "settings";

type OperatorDetail = "candles" | "symbols" | "evidence" | "btc" | "execution";

type Row = Record<string, any>;

type StructuralSnapshot = {
  lab: {
    name: string;
    root_path: string;
    output_path: string;
    has_run: boolean;
    empty_state?: string | null;
  };
  summary: Record<string, any>;
  summary_metrics: Record<string, any>;
  settings: Record<string, any>;
  symbols_config: Record<string, any>;
  profit_vault: Record<string, any>;
  report_markdown: string;
  artifact_freshness: Record<string, Record<string, any>>;
  available_symbols: string[];
  available_timeframes: string[];
  shadow_forward?: {
    mode?: string;
    canonical_data?: Record<string, any>;
    runtime_status?: Record<string, any>;
    scheduler?: Record<string, any>;
    catchup?: Record<string, any>;
    decisions?: Record<string, any>;
    simulated_trades?: Record<string, any>;
    net_cost_cockpit?: Record<string, any>;
    cost_truth?: Record<string, any>;
    target_curve?: Record<string, any>;
    safety?: Record<string, any>;
    artifacts?: Record<string, Record<string, any>>;
  };
  multi_symbol_forward?: {
    mode?: string;
    runtime_status?: Record<string, any>;
    scheduler?: Record<string, any>;
    evidence?: Record<string, any>;
    reduced_cap?: Record<string, any>;
    decisions?: Record<string, any>;
    operator_tape?: Record<string, any>;
    pnl_reference?: Record<string, any>;
    safety?: Record<string, any>;
    artifacts?: Record<string, Record<string, any>>;
  };
  execution_readiness?: {
    mode?: string;
    paper_scaffold_exists?: boolean;
    live_scaffold_exists?: boolean;
    paper_ready?: boolean;
    live_ready?: boolean;
    paper_blockers?: string[];
    live_blockers?: string[];
    capability_matrix?: Record<string, any>;
    preflight?: Record<string, any>;
    gate?: Record<string, any>;
    paper_validation_ready?: boolean;
    paper_allowed?: boolean;
    live_allowed?: boolean;
    real_money_allowed?: boolean;
    artifacts?: Record<string, Record<string, any>>;
  };
  trade_rows: Row[];
  trade_frequency_pnl?: TradeFrequencyPnlPayload;
  setup_rows: Row[];
  level_rows: Row[];
  liquidity_rows: Row[];
  cooldown_rows: Row[];
  pyramiding_rows: Row[];
  equity_rows: Row[];
  overview: {
    base_capital: number;
    active_trading_capital: number;
    locked_profit: number;
    floating_profit: number;
    current_equity: number;
    current_compounding_cycle: string;
    cooldown_state: string;
    total_return_pct: number;
    max_drawdown_pct: number;
    win_rate: number;
    profit_factor: number;
    profit_lock_count?: number;
    add_on_event_count?: number;
    cooldown_release_count?: number;
    r_multiple_summary: string;
  };
  structural_state?: {
    latest_trade?: Row;
    latest_setup?: Row;
    latest_cooldown_event?: Row;
    latest_pyramiding_event?: Row;
  };
  chart_points: {
    equity: Array<{ label?: string; value: number }>;
    locked_profit: Array<{ label?: string; value: number }>;
  };
  daily_structural_opportunity?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    top_opportunity_by_day?: Row[];
    candidate_rows?: Row[];
    participation_distribution?: Record<string, any>;
    sr_zone_report?: Record<string, any>;
    breakout_retest_report?: Record<string, any>;
    missed_report?: Record<string, any>;
    too_tight_report?: Record<string, any>;
    noise_chasing_report?: Record<string, any>;
    high_r_report?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  five_year_full_capital_audit?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    long_short_breakdown?: Row[];
    monthly_summary?: Row[];
    asymmetric_payoff?: Record<string, any>;
    moonshot_contribution?: Record<string, any>;
    scaling_safety?: Record<string, any>;
    failure_modes?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  long_short_edge_repair?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    long_edge_breakdown?: Row[];
    short_edge_breakdown?: Row[];
    archetype_expectancy_breakdown?: Row[];
    personality_expectancy_breakdown?: Row[];
    long_failure_modes?: Row[];
    short_success_modes?: Row[];
    moonshot_repeatability?: Row[];
    moonshot_dependency?: Record<string, any>;
    long_filters_research_candidates?: Record<string, any>;
    short_preservation_rules?: Record<string, any>;
    edge_repair_recommendation?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  long_damage_control_patch?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    patch_variant_summary?: Row[];
    patch_variant_trade_replay?: Row[];
    disabled_long_archetype_impact?: Row[];
    preserved_short_edge_impact?: Row[];
    moonshot_dependency_after_patch?: Record<string, any>;
    full_capital_compounding_after_patch?: Row[];
    drawdown_after_patch?: Row[];
    best_patch_candidate?: Record<string, any>;
    rejected_patch_candidates?: Row[] | Record<string, any>;
    research_only_patch_recommendation?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  frozen_patch_validation?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    frozen_patch_rules?: Record<string, any>;
    validation_window_summary?: Row[];
    year_by_year_validation?: Row[];
    regime_validation_summary?: Row[];
    walk_forward_validation?: Row[];
    out_of_sample_validation?: Row[];
    frozen_patch_trade_replay?: Row[];
    full_active_capital_validation_curve?: Row[];
    drawdown_validation_report?: Row[];
    moonshot_dependency_validation?: Record<string, any>;
    long_short_validation_breakdown?: Row[];
    validation_failure_modes?: Row[];
    promotion_gate_report?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  frozen_patch_forensic_integrity?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    artifact_lineage?: Record<string, any>;
    data_coverage?: Record<string, any>;
    sample_reuse?: Record<string, any>;
    leakage_risk?: Record<string, any>;
    frozen_rule_origin?: Record<string, any>;
    source_history_availability?: Record<string, any>;
    validation_gap?: Record<string, any>;
    required_next_replay_plan?: Record<string, any>;
    no_go_risks?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  broad_historical_structural_replay?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    source_data_coverage?: Record<string, any>;
    replay_window_manifest?: Record<string, any>;
    yearly_trade_counts?: Row[];
    monthly_trade_counts?: Row[];
    replay_health_report?: Record<string, any>;
    replay_failure_report?: Record<string, any>;
    data_gap_report?: Record<string, any>;
    no_future_leakage_checks?: Record<string, any>;
    generated_ledger_manifest?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  broad_frozen_patch_validation?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    raw_vs_patch?: Record<string, any>;
    raw_vs_patch_rows?: Row[];
    yearly_raw_vs_patch?: Row[];
    monthly_raw_vs_patch?: Row[];
    long_short_raw_vs_patch?: Record<string, any>;
    archetype_raw_vs_patch?: Row[];
    disabled_trade_impact?: Row[];
    preserved_trade_impact?: Row[];
    moonshot_dependency?: Record<string, any>;
    execution_cost_sensitivity?: Record<string, any>;
    drawdown_comparison?: Row[];
    profit_vault_comparison?: Record<string, any>;
    patch_survival_by_year?: Record<string, any>;
    no_go_risks?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  native_sr_aware_strict_stress_monte_carlo?: {
    summary?: Record<string, any>;
    status?: Record<string, any>;
    report_markdown?: string;
    frozen_variant?: Record<string, any>;
    pf_42_sanity?: Record<string, any>;
    pre_entry_rule_integrity?: Record<string, any>;
    stress_test_matrix?: Row[];
    rolling_5y_stress_summary?: Row[];
    monte_carlo_summary?: Record<string, any>;
    monte_carlo_distribution?: Row[];
    monte_carlo_drawdown_distribution?: Row[];
    mission_gap_report?: Record<string, any>;
    promotion_gate_report?: Record<string, any>;
    monte_carlo_ruin_risk?: Record<string, any>;
    next_research_recommendation?: Record<string, any>;
    metadata?: Record<string, any>;
  };
  warnings: string[];
};

const API_URL = (process.env.NEXT_PUBLIC_DASHBOARD_API_URL || "/dashboard-api").replace(/\/$/, "");

const VIEWS: Array<{
  key: StructuralView;
  label: string;
  href: string;
  icon: React.ReactNode;
  eyebrow: string;
}> = [
  {
    key: "overview",
    label: "Command",
    href: "/structural-lab",
    icon: <BarChart3 className="h-4 w-4" />,
    eyebrow: "capital rhythm",
  },
  {
    key: "market-replay",
    label: "Candles",
    href: "/structural-lab/market-replay",
    icon: <CandlestickChart className="h-4 w-4" />,
    eyebrow: "candle theatre",
  },
  {
    key: "structure-map",
    label: "Structure",
    href: "/structural-lab/structure-map",
    icon: <Layers3 className="h-4 w-4" />,
    eyebrow: "levels and liquidity",
  },
  {
    key: "profit-vault",
    label: "Research Vault",
    href: "/structural-lab/profit-vault",
    icon: <Vault className="h-4 w-4" />,
    eyebrow: "compounding discipline",
  },
  {
    key: "trade-review",
    label: "Trade Review",
    href: "/structural-lab/trade-review",
    icon: <Waves className="h-4 w-4" />,
    eyebrow: "forensics tape",
  },
  {
    key: "settings",
    label: "Settings",
    href: "/structural-lab/settings",
    icon: <Settings2 className="h-4 w-4" />,
    eyebrow: "research config",
  },
];

const OPERATOR_DETAIL_TABS: Array<{
  key: OperatorDetail;
  label: string;
  description: string;
}> = [
  {
    key: "candles",
    label: "Candle Wall",
    description: "Live chart, timeframes, indicators, markers and decision tape.",
  },
  {
    key: "symbols",
    label: "Symbol Health",
    description: "Active universe 1m quality, rows, 15m and 1H formation.",
  },
  {
    key: "evidence",
    label: "Forward Evidence",
    description: "Six-month observation slots, scheduler and capped-capital result.",
  },
  {
    key: "btc",
    label: "BTC Baseline",
    description: "Original shadow-forward baseline and net-cost truth.",
  },
  {
    key: "execution",
    label: "Execution Gates",
    description: "Paper/live safety scaffold, blockers and permission state.",
  },
];

const fetcher = async <T,>(url: string): Promise<T> => {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
};

function formatMoney(value: unknown) {
  const numeric = Number(value ?? 0);
  if (Number.isNaN(numeric)) {
    return "n/a";
  }
  const sign = numeric < 0 ? "-" : "";
  const absolute = Math.abs(numeric);
  const [integer, decimal] = absolute.toFixed(2).split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}€${grouped}.${decimal}`;
}

function formatPct(value: unknown, digits = 2) {
  return `${(Number(value ?? 0) * 100).toFixed(digits)}%`;
}

function number(value: unknown, digits = 2) {
  const numeric = Number(value ?? 0);
  if (!Number.isFinite(numeric)) {
    return "n/a";
  }
  return numeric.toFixed(digits);
}

function formatTime(value: unknown) {
  if (!value) {
    return "n/a";
  }
  const rawValue = String(value);
  const normalizedValue = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(rawValue)
    ? `${rawValue}Z`
    : rawValue;
  const asDate = new Date(normalizedValue);
  if (Number.isNaN(asDate.getTime())) {
    return rawValue;
  }
  const pad = (item: number) => String(item).padStart(2, "0");
  return `${asDate.getUTCFullYear()}-${pad(asDate.getUTCMonth() + 1)}-${pad(asDate.getUTCDate())} ${pad(asDate.getUTCHours())}:${pad(asDate.getUTCMinutes())}:${pad(asDate.getUTCSeconds())} UTC`;
}

function formatDuration(totalSeconds: number | null) {
  if (totalSeconds === null || Number.isNaN(totalSeconds)) {
    return "syncing";
  }
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(seconds).padStart(2, "0")}s`;
  }
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function compactPath(value: unknown, maxSegments = 3) {
  const raw = String(value ?? "n/a");
  if (!raw || raw === "n/a") return "n/a";
  return raw
    .split(" + ")
    .map((part) => {
      const normalized = part.replace(/\\/g, "/");
      const segments = normalized.split("/").filter(Boolean);
      if (segments.length <= maxSegments) return part;
      return `…/${segments.slice(-maxSegments).join("/")}`;
    })
    .join(" + ");
}

function secondsUntilNextIntervalRun(nowMs: number | null, intervalSeconds: number) {
  if (nowMs === null || !Number.isFinite(intervalSeconds) || intervalSeconds <= 0) {
    return null;
  }
  const nowSeconds = Math.floor(nowMs / 1000);
  const remainder = nowSeconds % intervalSeconds;
  return remainder === 0 ? intervalSeconds : intervalSeconds - remainder;
}

function toneForArtifact(status: string | undefined) {
  if (status === "healthy") {
    return "border-emerald-400/20 bg-emerald-400/10 text-emerald-200";
  }
  if (status === "stale" || status === "missing") {
    return "border-orange-400/20 bg-orange-400/10 text-orange-200";
  }
  return "border-white/10 bg-white/5 text-white/70";
}

function EmptyState({
  title,
  body,
}: {
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-[28px] border border-dashed border-white/14 bg-white/5 px-5 py-10 text-center">
      <div className="text-lg font-semibold text-white">{title}</div>
      <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-white/62">{body}</p>
    </div>
  );
}

function Section({
  eyebrow,
  title,
  children,
  className,
  source,
}: {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
  className?: string;
  source?: string;
}) {
  return (
    <section
      className={clsx(
        "cinematic-card render-contained relative overflow-hidden rounded-[30px] border border-white/10 bg-[linear-gradient(180deg,rgba(10,16,30,0.88),rgba(7,11,23,0.78))] p-5 shadow-[0_12px_36px_rgba(5,10,28,0.22)]",
        className,
      )}
    >
      <div className="mb-4">
        <div className="text-[11px] uppercase tracking-[0.3em] text-cyan-200/72">{eyebrow}</div>
        <h2 className="mt-2 text-xl font-semibold text-white">{title}</h2>
        {source ? (
          <div
            className="mt-2 flex min-w-0 max-w-full items-center gap-2 overflow-hidden rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs leading-5 text-white/55"
            title={source}
          >
            <span className="shrink-0 uppercase tracking-[0.22em] text-white/38">Source</span>
            <span className="min-w-0 truncate text-white/70">{compactPath(source, 4)}</span>
          </div>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function MetricCard({
  label,
  value,
  subtext,
  tone = "cyan",
}: {
  label: string;
  value: string;
  subtext?: string;
  tone?: "cyan" | "green" | "orange";
}) {
  const toneClass =
    tone === "green"
      ? "border-emerald-300/22 bg-[linear-gradient(180deg,rgba(9,45,38,0.72),rgba(8,20,23,0.9))]"
      : tone === "orange"
        ? "border-orange-300/22 bg-[linear-gradient(180deg,rgba(52,31,18,0.78),rgba(24,16,21,0.92))]"
        : "border-cyan-300/22 bg-[linear-gradient(180deg,rgba(8,45,62,0.72),rgba(7,19,34,0.9))]";
  return (
    <div className={clsx("cinematic-card rounded-[24px] border px-4 py-4", toneClass)}>
      <div className="text-[10px] uppercase tracking-[0.28em] text-white/55">{label}</div>
      <div className="mt-3 text-3xl font-semibold text-white">{value}</div>
      {subtext ? <div className="mt-2 text-sm text-white/60">{subtext}</div> : null}
    </div>
  );
}

function TableEmpty({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm text-white/58">
      {message}
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-w-full overflow-x-auto whitespace-pre-wrap break-words rounded-[24px] border border-white/10 bg-[#040915] p-4 text-xs leading-6 text-white/72">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

export function StructuralLabShell({
  view = "overview",
}: {
  view?: StructuralView;
}) {
  const { data, error } = useSWR<StructuralSnapshot>(
    `${API_URL}/api/structural-lab/snapshot`,
    fetcher,
    { refreshInterval: 30000, revalidateOnFocus: false },
  );
  const [clientNowMs, setClientNowMs] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setClientNowMs(Date.now());
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const rawAvailableSymbols = data?.available_symbols?.length ? data.available_symbols : ["BTCUSDT"];
  const availableTimeframes = data?.available_timeframes?.length ? data.available_timeframes : ["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"];
  const [symbol, setSymbol] = useState("ADAUSDT");
  const [timeframe, setTimeframe] = useState("1m");
  const [showResearchArchive, setShowResearchArchive] = useState(false);
  const [operatorDetail, setOperatorDetail] = useState<OperatorDetail>("candles");

  const selectedTimeframe = availableTimeframes.includes(timeframe) ? timeframe : availableTimeframes[0];
  const overview = data?.overview;
  const warningList = data?.warnings ?? [];
  const activeView = VIEWS.find((item) => item.key === view) ?? VIEWS[0];
  const compactHero = true;
  const tradeRows = data?.trade_rows ?? [];
  const levelRows = data?.level_rows ?? [];
  const liquidityRows = data?.liquidity_rows ?? [];
  const setupRows = data?.setup_rows ?? [];
  const cooldownRows = data?.cooldown_rows ?? [];
  const pyramidingRows = data?.pyramiding_rows ?? [];
  const latestTrade = tradeRows[tradeRows.length - 1] ?? null;
  const latestSetup = setupRows[setupRows.length - 1] ?? null;
  const latestCooldownEvent = data?.structural_state?.latest_cooldown_event ?? null;
  const latestPyramidingEvent = data?.structural_state?.latest_pyramiding_event ?? null;
  const dailyOpportunity = data?.daily_structural_opportunity;
  const dailyOpportunitySummary = dailyOpportunity?.summary ?? {};
  const dailyOpportunityRows = dailyOpportunity?.top_opportunity_by_day ?? [];
  const dailyOpportunityMetadata = dailyOpportunity?.metadata ?? {};
  const fiveYearAudit = data?.five_year_full_capital_audit;
  const fiveYearSummary = fiveYearAudit?.summary ?? {};
  const fiveYearMetadata = fiveYearAudit?.metadata ?? {};
  const fiveYearBreakdown = fiveYearAudit?.long_short_breakdown ?? [];
  const fiveYearMoonshot = fiveYearAudit?.moonshot_contribution ?? {};
  const fiveYearScalingSafety = fiveYearAudit?.scaling_safety ?? {};
  const fiveYearFailureModes = fiveYearAudit?.failure_modes ?? {};
  const longShortRepair = data?.long_short_edge_repair;
  const longShortRepairSummary = longShortRepair?.summary ?? {};
  const longShortRepairRecommendation = longShortRepair?.edge_repair_recommendation ?? {};
  const longShortRepairArchetypes = longShortRepair?.archetype_expectancy_breakdown ?? [];
  const longDamageControlPatch = data?.long_damage_control_patch;
  const longDamageControlPatchSummary = longDamageControlPatch?.summary ?? {};
  const longDamageControlPatchBest = longDamageControlPatch?.best_patch_candidate ?? {};
  const longDamageControlPatchVariants = longDamageControlPatch?.patch_variant_summary ?? [];
  const frozenPatchValidation = data?.frozen_patch_validation;
  const frozenPatchValidationSummary = frozenPatchValidation?.summary ?? {};
  const frozenPatchPromotionGate = frozenPatchValidation?.promotion_gate_report ?? {};
  const frozenPatchValidationWindows = frozenPatchValidation?.validation_window_summary ?? [];
  const frozenPatchYearRows = frozenPatchValidation?.year_by_year_validation ?? [];
  const frozenPatchWalkForward = frozenPatchValidation?.walk_forward_validation ?? [];
  const frozenPatchForensicIntegrity = data?.frozen_patch_forensic_integrity;
  const frozenPatchForensicSummary = frozenPatchForensicIntegrity?.summary ?? {};
  const frozenPatchForensicLineage = frozenPatchForensicIntegrity?.artifact_lineage ?? {};
  const frozenPatchForensicCoverage = frozenPatchForensicIntegrity?.data_coverage ?? {};
  const frozenPatchForensicSampleReuse = frozenPatchForensicIntegrity?.sample_reuse ?? {};
  const frozenPatchForensicLeakage = frozenPatchForensicIntegrity?.leakage_risk ?? {};
  const frozenPatchForensicGap = frozenPatchForensicIntegrity?.validation_gap ?? {};
  const frozenPatchForensicNextReplay = frozenPatchForensicIntegrity?.required_next_replay_plan ?? {};
  const frozenPatchForensicNoGoRisks = frozenPatchForensicIntegrity?.no_go_risks ?? {};
  const broadHistoricalReplay = data?.broad_historical_structural_replay;
  const broadHistoricalReplaySummary = broadHistoricalReplay?.summary ?? {};
  const broadHistoricalReplayCoverage = broadHistoricalReplay?.source_data_coverage ?? {};
  const broadHistoricalReplayHealth = broadHistoricalReplay?.replay_health_report ?? {};
  const broadHistoricalReplayLeakage = broadHistoricalReplay?.no_future_leakage_checks ?? {};
  const broadHistoricalReplayManifest = broadHistoricalReplay?.generated_ledger_manifest ?? {};
  const broadFrozenPatchValidation = data?.broad_frozen_patch_validation;
  const broadFrozenPatchSummary = broadFrozenPatchValidation?.summary ?? {};
  const broadFrozenPatchRawVsPatch = broadFrozenPatchValidation?.raw_vs_patch ?? {};
  const broadFrozenPatchYearly = broadFrozenPatchValidation?.yearly_raw_vs_patch ?? [];
  const broadFrozenPatchMoonshot = broadFrozenPatchValidation?.moonshot_dependency ?? {};
  const broadFrozenPatchExecution = broadFrozenPatchValidation?.execution_cost_sensitivity ?? {};
  const broadFrozenPatchNoGo = broadFrozenPatchValidation?.no_go_risks ?? {};
  const nativeStrictStress = data?.native_sr_aware_strict_stress_monte_carlo;
  const nativeStrictStressSummary = nativeStrictStress?.summary ?? {};
  const nativeStrictStressFrozen = nativeStrictStress?.frozen_variant ?? {};
  const nativeStrictStressPf = nativeStrictStress?.pf_42_sanity ?? {};
  const nativeStrictStressIntegrity = nativeStrictStress?.pre_entry_rule_integrity ?? {};
  const nativeStrictStressMonteCarlo = nativeStrictStress?.monte_carlo_summary ?? {};
  const nativeStrictStressMissionGap = nativeStrictStress?.mission_gap_report ?? {};
  const nativeStrictStressPromotion = nativeStrictStress?.promotion_gate_report ?? {};
  const nativeStrictStressNextStep = nativeStrictStress?.next_research_recommendation ?? {};
  const nativeStrictStressMeta = nativeStrictStress?.metadata ?? {};
  const nativeStrictStressReferenceMode =
    nativeStrictStressSummary?.monte_carlo_reference_mode && nativeStrictStressMonteCarlo?.modes
      ? nativeStrictStressMonteCarlo.modes[nativeStrictStressSummary.monte_carlo_reference_mode] ?? {}
      : {};
  const shadowForward = data?.shadow_forward;
  const shadowCanonical = shadowForward?.canonical_data ?? {};
  const shadowScheduler = shadowForward?.scheduler ?? {};
  const shadowCatchup = shadowForward?.catchup ?? {};
  const shadowDecisions = shadowForward?.decisions ?? {};
  const shadowTrades = shadowForward?.simulated_trades ?? {};
  const shadowNetCost = shadowForward?.net_cost_cockpit ?? {};
  const shadowSafety = shadowForward?.safety ?? {};
  const shadowCostTruth = shadowForward?.cost_truth ?? {};
  const shadowTargetCurve = shadowForward?.target_curve ?? {};
  const shadowRuntimeStatus = shadowForward?.runtime_status ?? {};
  const multiSymbolForward = data?.multi_symbol_forward;
  const multiSymbolRuntime = multiSymbolForward?.runtime_status ?? {};
  const multiSymbolScheduler = multiSymbolForward?.scheduler ?? {};
  const multiSymbolEvidence = multiSymbolForward?.evidence ?? {};
  const multiSymbolReducedCap = multiSymbolForward?.reduced_cap ?? {};
  const multiSymbolDecisions = multiSymbolForward?.decisions ?? {};
  const multiSymbolOperatorTape = multiSymbolForward?.operator_tape ?? {};
  const multiSymbolPnlReference = multiSymbolForward?.pnl_reference ?? {};
  const researchAfterTax = multiSymbolPnlReference.research_after_tax ?? {};
  const holdoutAfterTax = multiSymbolPnlReference.holdout_after_tax ?? {};
  const operatorSymbolTape = Array.isArray(multiSymbolOperatorTape.symbol_tape)
    ? multiSymbolOperatorTape.symbol_tape
    : [];
  const multiSymbolResults = Array.isArray(multiSymbolRuntime.symbol_results)
    ? multiSymbolRuntime.symbol_results
    : [];
  const tradeTriggersLastRun = Number(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0);
  const tradeEmailsLastRun = Number(multiSymbolRuntime.multi_asset_trade_trigger_emails_sent_this_run ?? 0);
  const activeRuntimePnlEur = Number(multiSymbolOperatorTape.active_runtime_pnl_eur ?? 0);
  const activeOpenPositions = Number(multiSymbolOperatorTape.active_open_positions ?? 0);
  const activeExecutedTrades = tradeTriggersLastRun;
  const activeRuntimeSymbols = multiSymbolResults.map((row) => String(row?.symbol ?? "").toUpperCase()).filter(Boolean);
  const preferredRuntimeSymbols = activeRuntimeSymbols.length ? activeRuntimeSymbols : rawAvailableSymbols.map((item) => String(item).toUpperCase());
  const availableSymbols = Array.from(new Set([...preferredRuntimeSymbols, ...rawAvailableSymbols.map((item) => String(item).toUpperCase())]));
  const selectedSymbol = activeRuntimeSymbols.length
    ? activeRuntimeSymbols.includes(symbol)
      ? symbol
      : activeRuntimeSymbols[0]
    : availableSymbols.includes(symbol)
      ? symbol
      : availableSymbols[0] ?? "BTCUSDT";
  const selectedSymbolRuntime = multiSymbolResults.find((row) => String(row?.symbol ?? "").toUpperCase() === selectedSymbol);
  const selectedSymbolUsesActiveRuntime = activeRuntimeSymbols.includes(selectedSymbol);
  useEffect(() => {
    if (view !== "market-replay" || !activeRuntimeSymbols.length) {
      return;
    }
    const normalizedSymbol = String(symbol ?? "").toUpperCase();
    if (!activeRuntimeSymbols.includes(normalizedSymbol)) {
      setSymbol(activeRuntimeSymbols[0]);
    }
  }, [activeRuntimeSymbols, symbol, view]);
  const executionReadiness = data?.execution_readiness ?? {};
  const executionMatrix = executionReadiness.capability_matrix ?? {};
  const executionGate = executionReadiness.gate ?? {};
  const shadowCanonicalPath = String(shadowCanonical.path ?? "structural_compounding_lab/data_storage/BTCUSDT/1m/btcusdt_1m_canonical_shadow_forward.csv");
  const runtimeStatusPath = String(shadowForward?.artifacts?.latest_status?.path ?? "structural_compounding_lab/output/forward_validation_runtime/latest_status.json");
  const decisionLedgerPath = String(shadowDecisions.ledger_path ?? "structural_compounding_lab/output/forward_validation_runtime/ledger/forward_decision_ledger.csv");
  const simulatedTradeLedgerPath = String(shadowTrades.ledger_path ?? "structural_compounding_lab/output/forward_validation_runtime/ledger/forward_simulated_trade_ledger.csv");
  const timeframeOptions = availableTimeframes.filter((item) => typeof item === "string" && item.trim().length > 0);
  const nowDate = clientNowMs === null ? null : new Date(clientNowMs);
  const secondsIntoMinute = nowDate ? nowDate.getUTCSeconds() : 0;
  const candleCloseCountdown = clientNowMs === null ? null : 60 - secondsIntoMinute;
  const candleProgressPct = clientNowMs === null ? 0 : Math.min(100, Math.max(0, (secondsIntoMinute / 60) * 100));
  const multiSchedulerIntervalSeconds = Number(multiSymbolScheduler.run_interval_seconds ?? 300);
  const multiSchedulerCountdown = secondsUntilNextIntervalRun(clientNowMs, multiSchedulerIntervalSeconds);
  const multiRuntimeIsGreen = String(multiSymbolRuntime.status_color ?? "").toUpperCase() === "GREEN";
  const paperReady = Boolean(executionReadiness.paper_ready);
  const liveReady = Boolean(executionReadiness.live_ready);
  const latestArtifacts = useMemo(() => {
    const freshness = data?.artifact_freshness ?? {};
    return Object.entries(freshness);
  }, [data?.artifact_freshness]);

  const overviewContent = (
    <div className="grid gap-5">
      <div className="grid gap-4 xl:grid-cols-[1.25fr_0.75fr]">
        <div className="relative overflow-hidden rounded-[34px] border border-emerald-300/22 bg-[radial-gradient(circle_at_18%_18%,rgba(16,185,129,0.18),transparent_32%),linear-gradient(135deg,rgba(4,18,28,0.96),rgba(3,8,18,0.92))] p-6 shadow-[0_18px_48px_rgba(5,150,105,0.10)]">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div className="text-[11px] uppercase tracking-[0.34em] text-emerald-100/78">Active runtime truth</div>
              <h2 className="mt-3 text-3xl font-semibold text-white">
                {activeExecutedTrades > 0 ? "Trade activity recorded" : "No trade executed"}
              </h2>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-white/66">
                The active multi-symbol scheduler has processed market data and decision slots, but it has not recorded
                a trade trigger in the latest runtime check. Therefore active runtime PnL is shown as zero. Research,
                backtest, and BTC baseline equity are still available, but they are not live profit.
              </p>
            </div>
            <div className="rounded-[28px] border border-white/12 bg-white/6 px-5 py-4 text-right">
              <div className="text-[10px] uppercase tracking-[0.28em] text-white/50">Active PnL</div>
              <div className="mt-2 text-4xl font-semibold text-white">{formatMoney(activeRuntimePnlEur)}</div>
              <div className="mt-1 text-sm text-white/54">runtime/live execution only</div>
            </div>
          </div>
          <div className="mt-6 grid gap-3 md:grid-cols-4">
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Open positions</div>
              <div className="mt-2 text-2xl font-semibold text-white">{activeOpenPositions}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Trade triggers</div>
              <div className="mt-2 text-2xl font-semibold text-white">{String(activeExecutedTrades)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Trigger emails</div>
              <div className="mt-2 text-2xl font-semibold text-white">{String(tradeEmailsLastRun)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Real-money path</div>
              <div className="mt-2 text-2xl font-semibold text-white">OFF</div>
            </div>
          </div>
        </div>

        <div className="rounded-[34px] border border-amber-300/18 bg-[linear-gradient(145deg,rgba(48,30,12,0.68),rgba(8,11,21,0.92))] p-6">
          <div className="text-[11px] uppercase tracking-[0.34em] text-amber-100/80">Research numbers vault</div>
          <div className="mt-3 text-2xl font-semibold text-white">Not live PnL</div>
          <p className="mt-3 text-sm leading-7 text-white/62">
            Values such as {formatMoney(shadowNetCost.current_net_cost_diagnostic_equity)} and the legacy
            capital/vault numbers are archived diagnostic outputs. They explain the research baseline; they do not
            mean the scheduler made money today.
          </p>
          <button
            type="button"
            onClick={() => setOperatorDetail("btc")}
            className="mt-5 rounded-2xl border border-amber-300/24 bg-amber-400/12 px-4 py-2 text-sm font-medium text-amber-50 transition hover:bg-amber-400/18"
          >
            Open BTC / research baseline
          </button>
        </div>
      </div>

      <Section
        eyebrow="Active multi-symbol runtime"
        title="Live 1m Ingestion, Resampling, Quality And Decision Slots"
        source={String(multiSymbolDecisions.runtime_root ?? "structural_compounding_lab/output/multi_symbol_forward_runtime_earned_parallel_slots")}
      >
        <div className="grid gap-4 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Runtime status"
              value={String(multiSymbolRuntime.status_color ?? "n/a")}
              subtext={`${String(multiSymbolRuntime.symbols_clean ?? 0)} / ${String(multiSymbolRuntime.symbols_checked ?? 0)} symbols clean`}
              tone={multiRuntimeIsGreen ? "green" : "orange"}
            />
            <MetricCard
              label="Latest safe 1m"
              value={formatTime(multiSymbolRuntime.latest_safe_1m_timestamp)}
              subtext={`${String(multiSymbolRuntime.total_appended_rows ?? 0)} rows appended last run`}
              tone="cyan"
            />
            <MetricCard
              label="Decision slots"
              value={String(multiSymbolDecisions.total_decision_slots ?? 0)}
              subtext={`new this run ${String(multiSymbolRuntime.total_new_decision_rows ?? 0)} / dupes ${String(multiSymbolRuntime.decision_ledger_duplicate_keys ?? 0)}`}
            />
            <MetricCard
              label="Trade triggers"
              value={String(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0)}
              subtext={`${String(multiSymbolRuntime.multi_asset_trade_trigger_emails_sent_this_run ?? 0)} emails sent last run`}
              tone={Number(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0) > 0 ? "orange" : "green"}
            />
          </div>

          <div className="rounded-[26px] border border-cyan-300/14 bg-cyan-400/8 p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-100/70">Selected chart source</div>
                <div className="mt-2 text-xl font-semibold text-white">{selectedSymbol} / {selectedTimeframe}</div>
              </div>
              <span className={clsx(
                "rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.22em]",
                selectedSymbolUsesActiveRuntime
                  ? "border-emerald-300/24 bg-emerald-400/12 text-emerald-100"
                  : "border-orange-300/24 bg-orange-400/12 text-orange-100",
              )}>
                {selectedSymbolUsesActiveRuntime ? "active runtime tape" : "fallback/historical tape"}
              </span>
            </div>
            <div className="mt-4 grid gap-2 text-sm text-white/66 sm:grid-cols-2">
              <div>Runtime rows: <span className="font-semibold text-white">{String(selectedSymbolRuntime?.rows_after ?? "n/a")}</span></div>
              <div>Complete 15m / 1H: <span className="font-semibold text-white">{String(selectedSymbolRuntime?.complete_15m_bars ?? "n/a")} / {String(selectedSymbolRuntime?.complete_1h_bars ?? "n/a")}</span></div>
              <div>Last timestamp: <span className="font-semibold text-white">{formatTime(selectedSymbolRuntime?.latest_safe_1m_timestamp)}</span></div>
              <div>Quality: <span className="font-semibold text-white">{selectedSymbolRuntime?.quality?.clean ? "clean" : selectedSymbolUsesActiveRuntime ? "check" : "n/a"}</span></div>
            </div>
          </div>
        </div>

        <div className="mt-5 flex gap-2 overflow-x-auto pb-1">
          {multiSymbolResults.map((row) => {
            const rowSymbol = String(row.symbol ?? "").toUpperCase();
            const clean = Boolean(row.quality?.clean);
            const active = rowSymbol === selectedSymbol;
            return (
              <button
                key={`rail-${rowSymbol}`}
                type="button"
                onClick={() => setSymbol(rowSymbol)}
                className={clsx(
                  "min-w-[122px] rounded-2xl border px-3 py-2 text-left transition",
                  active
                    ? "border-cyan-300/40 bg-cyan-400/14 text-white"
                    : clean
                      ? "border-emerald-300/16 bg-emerald-400/8 text-white/72 hover:border-cyan-300/24"
                      : "border-orange-300/18 bg-orange-400/10 text-orange-100",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{rowSymbol}</span>
                  <span className={clsx("h-2 w-2 rounded-full", clean ? "bg-emerald-300" : "bg-orange-300")} />
                </div>
                <div className="mt-1 text-[11px] uppercase tracking-[0.16em] text-white/42">
                  {String(row.complete_1h_bars ?? 0)} 1H bars
                </div>
              </button>
            );
          })}
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-5">
          {OPERATOR_DETAIL_TABS.map((item) => {
            const active = operatorDetail === item.key;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setOperatorDetail(item.key)}
                className={clsx(
                  "rounded-[22px] border px-4 py-3 text-left transition hover:-translate-y-0.5",
                  active
                    ? "border-cyan-300/34 bg-cyan-400/14 text-white shadow-[0_0_24px_rgba(34,211,238,0.10)]"
                    : "border-white/10 bg-white/5 text-white/66 hover:border-cyan-300/20 hover:bg-white/8",
                )}
              >
                <div className="text-sm font-semibold">{item.label}</div>
                <div className="mt-1 text-xs leading-5 text-white/48">{item.description}</div>
              </button>
            );
          })}
        </div>

        {operatorDetail === "symbols" ? (
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {multiSymbolResults.map((row) => {
            const rowSymbol = String(row.symbol ?? "").toUpperCase();
            const quality = row.quality ?? {};
            const clean = Boolean(quality.clean);
            const active = rowSymbol === selectedSymbol;
            return (
              <button
                key={rowSymbol}
                type="button"
                onClick={() => setSymbol(rowSymbol)}
                className={clsx(
                  "rounded-[24px] border p-4 text-left transition hover:-translate-y-0.5",
                  active
                    ? "border-cyan-300/35 bg-cyan-400/14 shadow-[0_0_28px_rgba(34,211,238,0.12)]"
                    : clean
                      ? "border-emerald-300/14 bg-emerald-400/7 hover:border-cyan-300/22"
                      : "border-orange-300/20 bg-orange-400/10",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-lg font-semibold text-white">{rowSymbol}</div>
                    <div className="mt-1 text-xs uppercase tracking-[0.18em] text-white/42">click to load chart</div>
                  </div>
                  <span className={clsx(
                    "rounded-full border px-2 py-1 text-[10px] uppercase tracking-[0.18em]",
                    clean ? "border-emerald-300/20 bg-emerald-400/12 text-emerald-100" : "border-orange-300/20 bg-orange-400/12 text-orange-100",
                  )}>
                    {clean ? "clean" : "warn"}
                  </span>
                </div>
                <div className="mt-4 grid gap-2 text-xs text-white/58">
                  <div className="flex justify-between gap-3"><span>latest 1m</span><span className="text-white/78">{formatTime(row.latest_safe_1m_timestamp)}</span></div>
                  <div className="flex justify-between gap-3"><span>rows</span><span className="text-white/78">{String(row.rows_after ?? quality.rows ?? 0)}</span></div>
                  <div className="flex justify-between gap-3"><span>15m / 1H</span><span className="text-white/78">{String(row.complete_15m_bars ?? 0)} / {String(row.complete_1h_bars ?? 0)}</span></div>
                  <div className="flex justify-between gap-3"><span>gaps / dupes / OHLC</span><span className="text-white/78">{String(quality.gap_count ?? 0)} / {String(quality.duplicate_count ?? 0)} / {String(quality.ohlc_failure_count ?? 0)}</span></div>
                </div>
              </button>
            );
          })}
        </div>
        ) : null}
      </Section>

      {operatorDetail === "candles" ? (
      <Section
        eyebrow="Primary live market wall"
        title="Active Multi-Symbol Candles, Timeframes, Trades And Decisions"
        source={`${String(multiSymbolDecisions.runtime_root ?? "active runtime root")} + ${String(multiSymbolDecisions.ledger_path ?? decisionLedgerPath)} + /api/structural-lab/candles`}
      >
        <div className="mb-4 grid gap-4 xl:grid-cols-[1fr_auto] xl:items-center">
          <div className="space-y-2 text-sm leading-7 text-white/68">
            <div>
              This is the main operator view: closed 1m source candles, resampled timeframe boards, indicators,
              structure/liquidity overlays, trade markers, rejected-decision markers, pinned condition cards,
              zoom/pan, price-scale controls, and fullscreen mode.
            </div>
            <div className="text-white/52">
              Chart data refreshes every 5 seconds. Public visual extension can show candles ahead of the persisted
              scheduler checkpoint without mutating the canonical runtime file.
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {timeframeOptions.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setTimeframe(item)}
                className={clsx(
                  "rounded-full border px-4 py-2 text-xs uppercase tracking-[0.22em] transition",
                  selectedTimeframe === item
                    ? "border-cyan-300/32 bg-cyan-400/14 text-cyan-50"
                    : "border-white/10 bg-white/5 text-white/62 hover:border-cyan-300/18 hover:text-white",
                )}
              >
                {item}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-4 flex flex-wrap gap-3">
          <label className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/72">
            Symbol
            <select
              className="ml-3 bg-transparent text-white outline-none"
              value={selectedSymbol}
              onChange={(event) => setSymbol(event.target.value)}
            >
              {availableSymbols.map((item) => (
                <option key={item} value={item} className="bg-slate-950 text-white">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/72">
            Timeframe
            <select
              className="ml-3 bg-transparent text-white outline-none"
              value={selectedTimeframe}
              onChange={(event) => setTimeframe(event.target.value)}
            >
              {availableTimeframes.map((item) => (
                <option key={item} value={item} className="bg-slate-950 text-white">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <div className="rounded-full border border-cyan-300/16 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-100">
            Fullscreen, zoom, indicators, volume, trades, rejects, structure, and liquidity are inside the chart toolbar.
          </div>
        </div>

        <CandlePanel
          apiUrl={API_URL}
          endpointPath="/api/structural-lab/candles"
          panelLabel={`${selectedSymbolUsesActiveRuntime ? "Active Multi-Symbol Runtime" : "Shadow Forward"} Candle Wall / ${selectedSymbol} / ${selectedTimeframe}`}
          symbol={selectedSymbol}
          timeframe={selectedTimeframe}
          mode="structural_lab"
        />
      </Section>
      ) : null}

      {operatorDetail === "btc" ? (
      <Section
        eyebrow="Shadow-forward mode"
        title="Live Operator Cockpit"
        source={`${runtimeStatusPath} + ${shadowCanonicalPath} + ${decisionLedgerPath} + ${simulatedTradeLedgerPath}`}
      >
        <div className="grid gap-5">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Scheduler"
              value={String(shadowScheduler.status_color ?? shadowScheduler.health ?? "n/a")}
              subtext={`${String(shadowScheduler.cadence ?? "not installed")} / runtime flag ${String(shadowScheduler.runtime_internal_scheduler_installed_flag ?? "n/a")}`}
              tone={String(shadowScheduler.status_color ?? "").toUpperCase() === "GREEN" ? "green" : "orange"}
            />
            <MetricCard
              label="Latest closed 1m"
              value={formatTime(shadowCanonical.latest_closed_1m_candle)}
              subtext={`${String(shadowCanonical.row_count ?? 0)} canonical closed candles`}
              tone="green"
            />
            <MetricCard
              label="Forming 1m"
              value={formatTime(shadowCanonical.current_forming_1m_candle_start)}
              subtext={shadowCanonical.current_forming_1m_candle_persisted ? "persisted" : "not persisted until closed"}
              tone="cyan"
            />
            <MetricCard
              label="Closed-candle lag"
              value={`${Number(shadowCanonical.estimated_closed_candle_lag_minutes ?? 0).toFixed(0)}m`}
              subtext={`next expected ${formatTime(shadowCanonical.next_expected_closed_1m_candle)}`}
              tone={Number(shadowCanonical.estimated_closed_candle_lag_minutes ?? 0) <= 65 ? "green" : "orange"}
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Data health"
              value={`${String(shadowCanonical.gap_count ?? "n/a")} / ${String(shadowCanonical.duplicate_count ?? "n/a")} / ${String(shadowCanonical.ohlc_failure_count ?? "n/a")}`}
              subtext="gaps / duplicates / OHLC failures"
              tone={
                Number(shadowCanonical.gap_count ?? 1) === 0 &&
                Number(shadowCanonical.duplicate_count ?? 1) === 0 &&
                Number(shadowCanonical.ohlc_failure_count ?? 1) === 0
                  ? "green"
                  : "orange"
              }
            />
            <MetricCard
              label="Catch-up last run"
              value={`${String(shadowCatchup.rows_appended_last_run ?? 0)} candles`}
              subtext={`caught up ${String(shadowCatchup.caught_up_to_realtime ?? "n/a")} / outage recovery ${String(shadowCatchup.outage_recovery_used_last_run ?? "n/a")}`}
              tone={shadowCatchup.caught_up_to_realtime ? "green" : "orange"}
            />
            <MetricCard
              label="Decision ledger"
              value={String(shadowDecisions.total_decisions ?? 0)}
              subtext={`${String(shadowDecisions.accepted_decisions ?? 0)} accepted / ${String(shadowDecisions.rejected_decisions ?? 0)} rejected`}
              tone="cyan"
            />
            <MetricCard
              label="Simulated trades"
              value={String(shadowTrades.total_simulated_trades ?? 0)}
              subtext={`${String(shadowTrades.created_this_run ?? 0)} created last run / no order path`}
              tone="green"
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-[1fr_1fr_1fr]">
            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Net-cost mission cockpit</div>
              <div className="mt-3 text-lg font-semibold text-white">
                {formatMoney(shadowNetCost.current_net_cost_diagnostic_equity)}
              </div>
              <div className="mt-2">
                Basis: {String(shadowNetCost.primary_equity_basis ?? "n/a")}
              </div>
              <div>
                Target delta: {formatMoney(shadowNetCost.ahead_or_behind_target_using_net_cost_equity)}
              </div>
              <div>
                Actual / required monthly: {formatPct(shadowNetCost.actual_net_cost_monthly_growth)} / {formatPct(shadowNetCost.required_monthly_growth)}
              </div>
              <div className="mt-2 text-white/54">
                Gross reference only: {formatMoney(shadowNetCost.current_gross_diagnostic_equity_reference_only)}
              </div>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Runtime honesty</div>
              <div className="mt-3 text-lg font-semibold text-white">
                {String(shadowRuntimeStatus.status ?? "n/a")}
              </div>
              <div>Reason: {String(shadowRuntimeStatus.final_reason ?? "n/a")}</div>
              <div>Last run: {formatTime(shadowRuntimeStatus.run_finished_at)}</div>
              <div>Latest safe market candle: {formatTime(shadowCatchup.latest_safe_market_timestamp)}</div>
              <div>Last 1H decision: {formatTime(shadowDecisions.last_processed_1h_decision_timestamp)}</div>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Safety gates</div>
              <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1">
                <span>research only</span><span className="text-right text-white">{String(shadowSafety.research_only ?? "n/a")}</span>
                <span>paper ready</span><span className="text-right text-white">{String(shadowSafety.paper_validation_ready ?? "n/a")}</span>
                <span>paper allowed</span><span className="text-right text-white">{String(shadowSafety.paper_allowed ?? "n/a")}</span>
                <span>live allowed</span><span className="text-right text-white">{String(shadowSafety.live_allowed ?? "n/a")}</span>
                <span>order path</span><span className="text-right text-white">{String(shadowSafety.order_path_exists ?? "n/a")}</span>
                <span>broker path</span><span className="text-right text-white">{String(shadowSafety.broker_path_exists ?? "n/a")}</span>
              </div>
            </div>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/66">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Cost model truth</div>
              <div className="mt-3 text-white">{String(shadowCostTruth.classification ?? "n/a")}</div>
              <div className="mt-2">
                Band: {String(shadowCostTruth.cost_model_used?.band_name ?? "n/a")} / round trip bps {String(shadowCostTruth.cost_model_used?.total_round_trip_bps ?? "n/a")}
              </div>
              <div className="mt-2">
                Holdout net equity: {formatMoney(shadowCostTruth.sealed_holdout_net_cost_result?.net_cost_eur25k_holdout)}
              </div>
            </div>
            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/66">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Target curve</div>
              <div className="mt-3">
                {formatMoney(shadowTargetCurve.starting_diagnostic_equity)} → {formatMoney(shadowTargetCurve.target_equity)}
              </div>
              <div>Required multiple: {String(shadowTargetCurve.required_multiple ?? "n/a")}x</div>
              <div>Required monthly growth: {formatPct(shadowTargetCurve.exact_monthly_growth)}</div>
              <div className="mt-2 text-white/54">
                Strategy changed by target curve: {String(shadowTargetCurve.strategy_behavior_changed_by_target_curve ?? "n/a")}
              </div>
            </div>
          </div>
        </div>
      </Section>
      ) : null}

      {operatorDetail === "evidence" ? (
      <Section
        eyebrow="Multi-symbol forward engine"
        title="Nine-Symbol Research Scheduler + Evidence Gate"
        source="structural_compounding_lab/output/multi_symbol_forward_runtime_earned_parallel_slots/ + multi_symbol_six_month_forward_evidence_court_001/"
      >
        <div className="grid gap-5">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Runtime"
              value={String(multiSymbolRuntime.status_color ?? "n/a")}
              subtext={`${String(multiSymbolRuntime.symbols_clean ?? 0)} / ${String(multiSymbolRuntime.symbols_expected ?? 9)} symbols clean`}
              tone={multiRuntimeIsGreen ? "green" : "orange"}
            />
            <MetricCard
              label="Scheduler"
              value={multiSymbolScheduler.installed_plist_exists ? "INSTALLED" : "DRAFT"}
              subtext={`${String(multiSymbolScheduler.label ?? "multi-symbol")} / ${String(multiSymbolScheduler.run_interval_seconds ?? 300)}s`}
              tone={multiSymbolScheduler.installed_plist_exists ? "green" : "orange"}
            />
            <MetricCard
              label="Evidence"
              value={String(multiSymbolEvidence.minimum_complete_1h_slots ?? 0)}
              subtext={`${String(multiSymbolEvidence.remaining_1h_slots ?? "n/a")} hourly slots remaining`}
              tone="cyan"
            />
            <MetricCard
              label="Decision keys"
              value={String(multiSymbolEvidence.decision_ledger_duplicate_keys ?? multiSymbolRuntime.decision_ledger_duplicate_keys ?? 0)}
              subtext={`${String(multiSymbolDecisions.total_decision_slots ?? 0)} slots recorded`}
              tone={Number(multiSymbolEvidence.decision_ledger_duplicate_keys ?? multiSymbolRuntime.decision_ledger_duplicate_keys ?? 1) === 0 ? "green" : "orange"}
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Forward observation contract</div>
              <div className="mt-3 text-lg font-semibold text-white">
                {String(multiSymbolEvidence.classification ?? "n/a")}
              </div>
              <div>Observation: {String(multiSymbolEvidence.observation_status ?? "n/a")}</div>
              <div>Latest runtime candle: {formatTime(multiSymbolEvidence.latest_runtime_timestamp ?? multiSymbolRuntime.latest_safe_1m_timestamp)}</div>
              <div>Clean symbols: {String(multiSymbolEvidence.symbols_clean ?? multiSymbolRuntime.symbols_clean ?? 0)} / {String(multiSymbolEvidence.symbols_expected ?? multiSymbolRuntime.symbols_expected ?? 9)}</div>
              <div>Target hourly slots: {String(multiSymbolEvidence.target_complete_1h_slots ?? 4320)}</div>
              <div className="mt-2 text-white/54">Active freeze includes BTC as a ninth research symbol; this remains output-only and does not enable execution.</div>
            </div>

            <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
              <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Fill-calibrated Gear 1</div>
              <div className="mt-3 text-lg font-semibold text-white">
                {formatMoney(multiSymbolReducedCap.research_result?.ending_total_equity_after_tax)}
              </div>
              <div>Active cap: {formatMoney(multiSymbolReducedCap.active_cap_eur)}</div>
              <div>Holdout no-tax result: {formatMoney(multiSymbolReducedCap.holdout_result_no_tax?.ending_total_equity_after_tax)}</div>
              <div>Tax reserve: {formatMoney(multiSymbolReducedCap.research_result?.total_tax_reserved_or_withdrawn)}</div>
              <div className="mt-2 text-white/54">Current clean planning case: reduced caps, cost model, tax reserve, capped compounding.</div>
            </div>
          </div>
        </div>
      </Section>
      ) : null}

      {operatorDetail === "execution" ? (
      <Section
        eyebrow="Execution control"
        title="Paper / Live Bot Scaffold — Guarded State"
        source="structural_compounding_lab/output/execution_readiness/latest_execution_readiness.json"
      >
        <div className="grid gap-5">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              label="Paper scaffold"
              value={executionReadiness.paper_scaffold_exists ? "EXISTS" : "MISSING"}
              subtext={paperReady ? "paper gate ready" : "blocked by gates"}
              tone={paperReady ? "green" : "orange"}
            />
            <MetricCard
              label="Live scaffold"
              value={executionReadiness.live_scaffold_exists ? "EXISTS" : "MISSING"}
              subtext={liveReady ? "live gate ready" : "real money blocked"}
              tone={liveReady ? "green" : "orange"}
            />
            <MetricCard
              label="Order sender"
              value={String(executionMatrix.order_sender ?? "blocked")}
              subtext="no signed exchange requests"
              tone="orange"
            />
            <MetricCard
              label="Paper validation"
              value={executionReadiness.paper_validation_ready ? "READY" : "FALSE"}
              subtext={`paper ${String(executionReadiness.paper_allowed ?? false)} / live ${String(executionReadiness.live_allowed ?? false)}`}
              tone={executionReadiness.paper_validation_ready ? "orange" : "green"}
            />
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <div className="rounded-[24px] border border-orange-300/18 bg-orange-400/8 px-4 py-4 text-sm leading-7 text-white/70">
              <div className="text-[10px] uppercase tracking-[0.28em] text-orange-200/80">Paper blockers</div>
              <ul className="mt-3 list-disc space-y-1 pl-5">
                {(executionReadiness.paper_blockers?.length ? executionReadiness.paper_blockers : ["none"]).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
            <div className="rounded-[24px] border border-red-300/18 bg-red-400/8 px-4 py-4 text-sm leading-7 text-white/70">
              <div className="text-[10px] uppercase tracking-[0.28em] text-red-200/80">Live blockers</div>
              <ul className="mt-3 list-disc space-y-1 pl-5">
                {(executionReadiness.live_blockers?.length ? executionReadiness.live_blockers : ["none"]).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>

          <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/66">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div>May create paper trades: <span className="text-white">{String(executionGate.may_create_paper_trades ?? false)}</span></div>
              <div>May create live trades: <span className="text-white">{String(executionGate.may_create_live_trades ?? false)}</span></div>
              <div>May send orders: <span className="text-white">{String(executionGate.may_send_orders ?? false)}</span></div>
              <div>May use broker: <span className="text-white">{String(executionGate.may_use_broker ?? false)}</span></div>
            </div>
          </div>
        </div>
      </Section>
      ) : null}

      <Section
        eyebrow="Historical archive"
        title="Research Courts And Legacy Diagnostics"
        source="Historical output folders under structural_compounding_lab/output/"
      >
        <div className="grid gap-4 xl:grid-cols-[1fr_auto] xl:items-center">
          <div className="space-y-2 text-sm leading-7 text-white/68">
            <div>
              The cockpit above is the active operator surface: live closed candles, scheduler state, catch-up truth,
              decision ledgers, multi-symbol forward evidence, and execution gates.
            </div>
            <div className="text-white/52">
              The panels below are older forensic research courts. They stay available, but they are collapsed by
              default so the dashboard does not bury the live shadow-forward state under stale or missing archives.
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowResearchArchive((current) => !current)}
            className="rounded-2xl border border-cyan-300/24 bg-cyan-400/12 px-5 py-3 text-sm font-medium text-cyan-50 transition hover:border-cyan-200/45 hover:bg-cyan-400/18"
          >
            {showResearchArchive ? "Hide research archive" : "Show research archive"}
          </button>
        </div>
      </Section>

      {showResearchArchive ? (
        <>
      <Section
        eyebrow="Native strict validation"
        title="Native SR-Aware Strict Stress + Monte Carlo"
        source="structural_compounding_lab/output/native_sr_aware_strict_stress_monte_carlo_audit_001/"
      >
        {nativeStrictStressMeta?.read_only && nativeStrictStressSummary?.variant_name ? (
          <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              <MetricCard
                label="Frozen variant"
                value={String(nativeStrictStressFrozen?.variant_name ?? nativeStrictStressSummary?.variant_name ?? "n/a")}
                subtext={`${nativeStrictStressFrozen?.trade_count ?? nativeStrictStressSummary?.trade_count ?? 0} trades`}
              />
              <MetricCard
                label="PF sanity"
                value={String(nativeStrictStressPf?.classification ?? nativeStrictStressSummary?.pf_sanity_verdict ?? "n/a")}
                subtext={`reported PF ${Number(nativeStrictStressFrozen?.profit_factor ?? nativeStrictStressSummary?.normal_profit_factor ?? 0).toFixed(2)}`}
                tone="orange"
              />
              <MetricCard
                label="Integrity"
                value={String(nativeStrictStressIntegrity?.classification ?? nativeStrictStressSummary?.pre_entry_integrity_verdict ?? "n/a")}
                subtext="pre-entry only / read-only research"
                tone="green"
              />
              <MetricCard
                label="Normal equity"
                value={formatMoney(nativeStrictStressSummary?.normal_ending_equity)}
                subtext={`DD ${formatPct(nativeStrictStressSummary?.normal_max_drawdown_pct ?? 0)}`}
                tone="green"
              />
              <MetricCard
                label="MC p50"
                value={formatMoney(nativeStrictStressReferenceMode?.median_ending_equity)}
                subtext={`p25 ${formatMoney(nativeStrictStressReferenceMode?.p25_ending_equity)}`}
              />
              <MetricCard
                label="MC > €1M"
                value={formatPct(nativeStrictStressReferenceMode?.probability_end_above_1m ?? 0)}
                subtext={`> €500k ${formatPct(nativeStrictStressReferenceMode?.probability_end_above_500k ?? 0)}`}
                tone="cyan"
              />
            </div>
            <div className="grid gap-4">
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
                <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Promotion gate</div>
                <div className="mt-3 text-lg font-semibold text-white">
                  {String(nativeStrictStressPromotion?.classification ?? nativeStrictStressSummary?.promotion_gate_classification ?? "n/a")}
                </div>
                <div className="mt-3 text-white/62">
                  Mission gap: {String(nativeStrictStressMissionGap?.verdict ?? nativeStrictStressSummary?.mission_gap_verdict ?? "n/a")}
                </div>
                <div className="mt-3 text-white/62">
                  Ruin risk: {formatPct(nativeStrictStressReferenceMode?.probability_ruin_or_equity_below_50pct_start ?? 0)}
                </div>
                <div className="mt-3 text-white/62">
                  Next action: {String(nativeStrictStressNextStep?.next_action ?? nativeStrictStressSummary?.next_research_action ?? "n/a")}
                </div>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
                <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Reference mode</div>
                <div className="mt-3 text-white/62">
                  {String(nativeStrictStressSummary?.monte_carlo_reference_mode ?? "monthly_block_bootstrap")}
                </div>
                <div className="mt-2 text-white/62">
                  Simulations {String(nativeStrictStressSummary?.monte_carlo_simulation_count ?? 0)}
                </div>
                <div className="mt-2 text-white/62">
                  Rolling 5Y avg {formatMoney(nativeStrictStressSummary?.rolling_5y_average_ending_equity)}
                </div>
              </div>
            </div>
          </div>
        ) : (
          <TableEmpty message="No native strict stress + Monte Carlo audit found yet." />
        )}
      </Section>

      <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
        <Section eyebrow="Historical research curve" title="Equity And Vault Rhythm" source="structural_compounding_lab/output/equity.csv + structural_compounding_lab/output/profit_vault.json">
          {data?.chart_points?.equity?.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <div className="mb-2 text-sm text-white/62">Equity curve</div>
                <MiniLineChart points={data.chart_points.equity} tone="cyan" className="h-[210px]" />
              </div>
              <div>
                <div className="mb-2 text-sm text-white/62">Locked-profit progression</div>
                <MiniLineChart
                  points={data.chart_points.locked_profit.length ? data.chart_points.locked_profit : [{ value: 0 }, { value: 0 }]}
                  tone="orange"
                  className="h-[210px]"
                />
              </div>
            </div>
          ) : (
            <EmptyState
              title="No structural backtest run found yet"
              body="Once equity.csv and profit_vault.json exist, this panel will show the compounding curve, the protected-vault staircase, and the reset points between cycles."
            />
          )}
        </Section>

        <Section eyebrow="Historical structural artifacts" title="Legacy Structural KPI Stack" source="structural_compounding_lab/output/summary.json + structural_compounding_lab/output/profit_vault.json">
          <div className="grid gap-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/50">Total return</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatPct(overview?.total_return_pct)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/50">Max drawdown</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatPct(overview?.max_drawdown_pct)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/50">Win rate</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatPct(overview?.win_rate)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/50">Profit factor</div>
              <div className="mt-2 text-2xl font-semibold text-white">{Number(overview?.profit_factor ?? 0).toFixed(2)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/66">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/50">R multiple summary</div>
              <div className="mt-2 leading-6">{overview?.r_multiple_summary ?? "No R-multiple summary yet."}</div>
            </div>
          </div>
        </Section>
      </div>

      <Section eyebrow="5-Year Full Capital Audit" title="Long/Short Full Active Capital Compounding" source="structural_compounding_lab/output/five_year_compounding_audit_001/">
        {Object.keys(fiveYearSummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                label="Classification"
                value={String(fiveYearSummary.compounding_readiness_classification ?? "n/a")}
                subtext={fiveYearMetadata.classification ?? "research-only"}
                tone={
                  String(fiveYearSummary.compounding_readiness_classification ?? "").includes("NOT_READY")
                    ? "orange"
                    : "green"
                }
              />
              <MetricCard
                label="Ending capital"
                value={formatMoney(fiveYearSummary.ending_capital_under_full_active_capital_model)}
                subtext={`Start ${formatMoney(fiveYearSummary.starting_capital)}`}
                tone="green"
              />
              <MetricCard
                label="5Y conservative"
                value={formatMoney(fiveYearSummary.projected_5_year_capital_conservative)}
                subtext="40% of observed average monthly return"
              />
              <MetricCard
                label="5Y base case"
                value={formatMoney(fiveYearSummary.projected_5_year_capital_base_case)}
                subtext="Observed median monthly return"
                tone="green"
              />
              <MetricCard
                label="5Y aggressive"
                value={formatMoney(fiveYearSummary.projected_5_year_capital_aggressive)}
                subtext={fiveYearSummary.projection_is_extrapolation ? "extrapolation, not proof" : "research projection"}
                tone="orange"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
              <MetricCard label="Max drawdown" value={formatPct(fiveYearSummary.max_drawdown_pct)} subtext={formatMoney(fiveYearSummary.max_drawdown_eur)} tone="orange" />
              <MetricCard label="Worst day" value={formatMoney(fiveYearSummary.worst_day_pnl)} subtext={`${Number(fiveYearSummary.worst_day_R ?? 0).toFixed(2)}R`} tone="orange" />
              <MetricCard label="Best day" value={formatMoney(fiveYearSummary.best_day_pnl)} subtext={`${Number(fiveYearSummary.best_day_R ?? 0).toFixed(2)}R`} tone="green" />
              <MetricCard label="Trades / active day" value={String(Number(fiveYearSummary.average_trades_per_active_day ?? 0).toFixed(2))} subtext={`${String(fiveYearSummary.average_trades_per_day ?? 0)} per day`} />
              <MetricCard label="Moonshots 5R+" value={String(fiveYearSummary.moonshot_5R_plus_count ?? 0)} subtext={`${String(fiveYearSummary.moonshot_8R_plus_count ?? 0)} / ${String(fiveYearSummary.moonshot_10R_plus_count ?? 0)} at 8R+ / 10R+`} tone="green" />
              <MetricCard label="3 wins cover 7 losses" value={fiveYearSummary.can_3_winners_cover_7_losers ? "yes" : "no"} subtext={`moonshot pct ${formatPct(fiveYearSummary.moonshot_profit_contribution_pct)}`} tone={fiveYearSummary.can_3_winners_cover_7_losers ? "green" : "orange"} />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Direction contribution" title="Long / Short Expectancy Split" className="p-0">
                {fiveYearBreakdown.length ? (
                  <div className="overflow-x-auto px-5 py-5">
                    <table className="min-w-full text-left text-sm">
                      <thead className="text-white/45">
                        <tr>
                          <th className="pb-3 pr-4 font-medium">Side</th>
                          <th className="pb-3 pr-4 font-medium">Trades</th>
                          <th className="pb-3 pr-4 font-medium">Win rate</th>
                          <th className="pb-3 pr-4 font-medium">Avg R</th>
                          <th className="pb-3 pr-4 font-medium">Total R</th>
                          <th className="pb-3 pr-4 font-medium">PF</th>
                          <th className="pb-3 pr-4 font-medium">5R+ / 8R+ / 10R+</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fiveYearBreakdown.map((row, index) => (
                          <tr key={`${row.side ?? index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{String(row.side ?? "n/a").toUpperCase()}</td>
                            <td className="py-3 pr-4 text-white/68">{row.trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{formatPct(row.win_rate)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.avg_R ?? 0).toFixed(3)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.total_R ?? 0).toFixed(3)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.profit_factor ?? 0).toFixed(2)}</td>
                            <td className="py-3 pr-4 text-white/68">
                              {String(row.moonshot_5R_plus_count ?? 0)} / {String(row.moonshot_8R_plus_count ?? 0)} / {String(row.moonshot_10R_plus_count ?? 0)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No 5-year long/short compounding breakdown available yet." />
                )}
              </Section>

              <div className="grid gap-5">
                <Section eyebrow="Compounding safety" title="Survival / Vault / Cooldown">
                  <div className="grid gap-3">
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      full-capital survival: <span className="font-medium text-white">{fiveYearSummary.whether_full_active_capital_model_survives_observed_trade_sequence ? "true" : "false"}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      cooldown count: <span className="font-medium text-white">{String(fiveYearSummary.cooldown_count ?? 0)}</span> | profit locks: <span className="font-medium text-white">{String(fiveYearSummary.profit_lock_count ?? 0)}</span>
                    </div>
                    <div className="rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
                      profit vault delta vs no-vault: {formatMoney(fiveYearScalingSafety.profit_vault_delta_vs_no_vault_eur ?? 0)} | no-vault ending {formatMoney(fiveYearScalingSafety.ending_equity_without_profit_vault ?? 0)}
                    </div>
                    <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 text-sm text-orange-100">
                      longest loss streak {String(fiveYearScalingSafety.longest_loss_streak ?? 0)} | longest stop streak {String(fiveYearScalingSafety.longest_stop_streak ?? 0)}
                    </div>
                  </div>
                </Section>

                <Section eyebrow="Payoff geometry" title="Few Winners Vs Many Losses">
                  <div className="grid gap-3">
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      moonshot contribution: <span className="font-medium text-white">{formatPct(fiveYearMoonshot.moonshot_profit_contribution_pct ?? fiveYearSummary.moonshot_profit_contribution_pct)}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      few winners covered many losses: <span className="font-medium text-white">{String(fiveYearAudit?.asymmetric_payoff?.few_winners_cover_many_losses_count ?? 0)}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      moonshot-saved blocks: <span className="font-medium text-white">{String(fiveYearAudit?.asymmetric_payoff?.moonshot_saved_block_count ?? 0)}</span>
                    </div>
                    <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 text-sm text-orange-100">
                      failure warnings: {(fiveYearFailureModes.warnings ?? []).length ? String((fiveYearFailureModes.warnings ?? []).join(" | ")) : "none"}
                    </div>
                  </div>
                </Section>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No 5-year full-capital audit found yet"
            body="Once `five_year_compounding_audit_001` exists, this section will show the full active-capital long/short replay curve, directional contribution, moonshot dependence, and whether a few high-R winners can overpower frequent -1R losses."
          />
        )}
      </Section>

      <Section eyebrow="Long vs Short Edge Repair Audit" title="Directional Edge Forensics" source="structural_compounding_lab/output/long_short_edge_repair_audit_001/">
        {Object.keys(longShortRepairSummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
              <MetricCard
                label="Long total R"
                value={Number(longShortRepairSummary.long_total_R ?? 0).toFixed(2)}
                subtext={`PF ${Number(longShortRepairSummary.long_profit_factor ?? 0).toFixed(2)}`}
                tone="orange"
              />
              <MetricCard
                label="Short total R"
                value={Number(longShortRepairSummary.short_total_R ?? 0).toFixed(2)}
                subtext={`PF ${Number(longShortRepairSummary.short_profit_factor ?? 0).toFixed(2)}`}
                tone="green"
              />
              <MetricCard
                label="Long win rate"
                value={formatPct(longShortRepairSummary.long_win_rate)}
                subtext={`${String(longShortRepairSummary.long_trade_count ?? 0)} trades`}
                tone="orange"
              />
              <MetricCard
                label="Short win rate"
                value={formatPct(longShortRepairSummary.short_win_rate)}
                subtext={`${String(longShortRepairSummary.short_trade_count ?? 0)} trades`}
                tone="green"
              />
              <MetricCard
                label="Moonshot contribution"
                value={formatPct(longShortRepairSummary.moonshot_profit_contribution_pct_of_net)}
                subtext={`${String(longShortRepairSummary.moonshot_5R_plus_count ?? 0)} at 5R+`}
                tone="orange"
              />
              <MetricCard
                label="Next patch"
                value={String(longShortRepairSummary.recommended_next_research_patch ?? "n/a")}
                subtext="research-only recommendation"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[24px] border border-emerald-300/20 bg-emerald-400/10 px-4 py-4">
                <div className="text-[10px] uppercase tracking-[0.22em] text-emerald-100/72">Best long archetype</div>
                <div className="mt-3 text-sm leading-6 text-white">{String(longShortRepairSummary.best_long_archetype ?? "n/a")}</div>
              </div>
              <div className="rounded-[24px] border border-orange-300/20 bg-orange-400/10 px-4 py-4">
                <div className="text-[10px] uppercase tracking-[0.22em] text-orange-100/72">Worst long archetype</div>
                <div className="mt-3 text-sm leading-6 text-white">{String(longShortRepairSummary.worst_long_archetype ?? "n/a")}</div>
              </div>
              <div className="rounded-[24px] border border-emerald-300/20 bg-emerald-400/10 px-4 py-4">
                <div className="text-[10px] uppercase tracking-[0.22em] text-emerald-100/72">Best short archetype</div>
                <div className="mt-3 text-sm leading-6 text-white">{String(longShortRepairSummary.best_short_archetype ?? "n/a")}</div>
              </div>
              <div className="rounded-[24px] border border-orange-300/20 bg-orange-400/10 px-4 py-4">
                <div className="text-[10px] uppercase tracking-[0.22em] text-orange-100/72">Worst short archetype</div>
                <div className="mt-3 text-sm leading-6 text-white">{String(longShortRepairSummary.worst_short_archetype ?? "n/a")}</div>
              </div>
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Patch guidance" title="Read-only recommendation" className="p-0">
                <div className="space-y-3 px-5 py-5 text-sm text-white/68">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Current problem</div>
                    <div className="mt-2 leading-6 text-white/80">{String(longShortRepairRecommendation.current_problem ?? "n/a")}</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Recommended patch</div>
                    <div className="mt-2 text-lg font-semibold text-cyan-100">{String(longShortRepairRecommendation.recommended_next_research_patch ?? "n/a")}</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 leading-7">
                    <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Moonshot stress</div>
                    <div className="mt-2">
                      Profit without moonshots: {formatMoney(longShortRepairSummary.profit_without_moonshots)}<br />
                      10R+ capped to 5R: {formatMoney(longShortRepairSummary.profit_with_10R_plus_capped_to_5R)}<br />
                      All 5R+ capped to 3R: {formatMoney(longShortRepairSummary.profit_with_all_5R_plus_capped_to_3R)}
                    </div>
                  </div>
                </div>
              </Section>

              <Section eyebrow="Expectancy map" title="Top archetype breakdown" className="p-0">
                {longShortRepairArchetypes.length ? (
                  <div className="overflow-x-auto px-5 py-5">
                    <table className="min-w-full text-left text-sm">
                      <thead className="text-white/45">
                        <tr>
                          <th className="pb-3 pr-4 font-medium">Side</th>
                          <th className="pb-3 pr-4 font-medium">Pullback</th>
                          <th className="pb-3 pr-4 font-medium">Personality</th>
                          <th className="pb-3 pr-4 font-medium">Trades</th>
                          <th className="pb-3 pr-4 font-medium">Total R</th>
                          <th className="pb-3 pr-4 font-medium">Label</th>
                        </tr>
                      </thead>
                      <tbody>
                        {longShortRepairArchetypes.slice(0, 10).map((row, index) => (
                          <tr key={`${row.side ?? "n/a"}-${row.pullback_type ?? "n/a"}-${index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{String(row.side ?? "n/a").toUpperCase()}</td>
                            <td className="py-3 pr-4 text-white/68">{row.pullback_type ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.personality_label ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.total_R ?? 0).toFixed(2)}</td>
                            <td className="py-3 pr-4 text-white/68">{row.expectancy_label ?? "n/a"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No long-vs-short edge repair audit has been generated yet." />
                )}
              </Section>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No long-vs-short edge repair audit found yet"
            body="Once `long_short_edge_repair_audit_001` exists, this section will show the asymmetric expectancy split, moonshot dependency stress, the best and worst archetypes on both sides, and the next research-only repair patch."
          />
        )}
      </Section>

      <Section eyebrow="Long Damage Control Patch Audit" title="Short Preservation / Long Damage Control" source="structural_compounding_lab/output/long_damage_control_patch_audit_001/">
        {Object.keys(longDamageControlPatchSummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
              <MetricCard
                label="Best patch candidate"
                value={String(longDamageControlPatchSummary.best_patch_candidate ?? "n/a")}
                subtext={String(longDamageControlPatchSummary.recommended_research_only_patch ?? "research-only")}
                tone="green"
              />
              <MetricCard
                label="Baseline ending capital"
                value={formatMoney(longDamageControlPatchSummary.baseline_ending_capital)}
                subtext={`PF ${Number(longDamageControlPatchSummary.baseline_profit_factor ?? 0).toFixed(2)}`}
                tone="orange"
              />
              <MetricCard
                label="Best patch ending capital"
                value={formatMoney(longDamageControlPatchSummary.best_patch_ending_capital)}
                subtext={`PF ${Number(longDamageControlPatchSummary.best_patch_profit_factor ?? 0).toFixed(2)}`}
                tone="green"
              />
              <MetricCard
                label="Baseline max DD"
                value={formatPct(longDamageControlPatchSummary.baseline_max_drawdown_pct)}
                subtext={`R ${Number(longDamageControlPatchSummary.baseline_total_R ?? 0).toFixed(2)}`}
                tone="orange"
              />
              <MetricCard
                label="Best patch max DD"
                value={formatPct(longDamageControlPatchSummary.best_patch_max_drawdown_pct)}
                subtext={`R ${Number(longDamageControlPatchSummary.best_patch_total_R ?? 0).toFixed(2)}`}
                tone="green"
              />
              <MetricCard
                label="Moonshot dependency"
                value={String(longDamageControlPatchSummary.moonshot_dependency_after_patch ?? "n/a")}
                subtext={String(longDamageControlPatchSummary.readiness_classification_after_patch ?? "n/a")}
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Long R removed"
                value={Number(longDamageControlPatchSummary.long_R_removed ?? 0).toFixed(2)}
                subtext="drag removed by patch"
                tone="green"
              />
              <MetricCard
                label="Short R preserved"
                value={Number(longDamageControlPatchSummary.short_R_preserved ?? 0).toFixed(2)}
                subtext={`${String(longDamageControlPatchBest.short_edge_preserved_pct ?? "n/a")} baseline share`}
                tone="green"
              />
              <MetricCard
                label="Trade count after patch"
                value={String(longDamageControlPatchSummary.trade_count_after_patch ?? 0)}
                subtext={`profit sans moonshots ${formatMoney(longDamageControlPatchSummary.profit_without_moonshots_after_patch)}`}
              />
              <MetricCard
                label="Readiness after patch"
                value={String(longDamageControlPatchSummary.readiness_classification_after_patch ?? "n/a")}
                subtext="research-only classification"
                tone="cyan"
              />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Patch recommendation" title="Read-only candidate view" className="p-0">
                <div className="space-y-3 px-5 py-5 text-sm text-white/68">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Recommended patch</div>
                    <div className="mt-2 text-lg font-semibold text-cyan-100">
                      {String(longDamageControlPatchSummary.recommended_research_only_patch ?? "n/a")}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 leading-7">
                    Baseline ending capital: {formatMoney(longDamageControlPatchSummary.baseline_ending_capital)}<br />
                    Best patch ending capital: {formatMoney(longDamageControlPatchSummary.best_patch_ending_capital)}<br />
                    Baseline PF: {Number(longDamageControlPatchSummary.baseline_profit_factor ?? 0).toFixed(2)}<br />
                    Best patch PF: {Number(longDamageControlPatchSummary.best_patch_profit_factor ?? 0).toFixed(2)}
                  </div>
                  <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 leading-7 text-orange-100">
                    This is diagnostic-only replay. No strategy, paper, live, allocator, or config mutation is exposed here.
                  </div>
                </div>
              </Section>

              <Section eyebrow="Variant scoreboard" title="Patch variants" className="p-0">
                {longDamageControlPatchVariants.length ? (
                  <div className="overflow-x-auto px-5 py-5">
                    <table className="min-w-full text-left text-sm">
                      <thead className="text-white/45">
                        <tr>
                          <th className="pb-3 pr-4 font-medium">Variant</th>
                          <th className="pb-3 pr-4 font-medium">Trades</th>
                          <th className="pb-3 pr-4 font-medium">End cap</th>
                          <th className="pb-3 pr-4 font-medium">PF</th>
                          <th className="pb-3 pr-4 font-medium">Max DD</th>
                          <th className="pb-3 pr-4 font-medium">Dependency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {longDamageControlPatchVariants.map((row, index) => (
                          <tr key={`${row.variant_name ?? index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{row.variant_name ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{formatMoney(row.ending_capital)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.profit_factor ?? 0).toFixed(2)}</td>
                            <td className="py-3 pr-4 text-white/68">{formatPct(row.max_drawdown_pct)}</td>
                            <td className="py-3 pr-4 text-white/68">{row.moonshot_dependency_label ?? "n/a"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No long damage control patch audit has been generated yet." />
                )}
              </Section>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No long damage control patch audit found yet"
            body="Once `long_damage_control_patch_audit_001` exists, this section will compare baseline versus research-only long-filter / short-preservation patch variants, including compounding, drawdown, and moonshot dependency."
          />
        )}
      </Section>

      <Section eyebrow="Frozen Patch Multi-Year Validation" title="Frozen Patch Proof Audit" source="structural_compounding_lab/output/frozen_patch_validation_audit_001/">
        {Object.keys(frozenPatchValidationSummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
              <MetricCard
                label="Frozen patch candidate"
                value={String(frozenPatchValidationSummary.frozen_patch_candidate ?? "n/a")}
                subtext={String(frozenPatchValidationSummary.promotion_gate_classification ?? "research-only")}
                tone="green"
              />
              <MetricCard
                label="Current sample end cap"
                value={formatMoney(longDamageControlPatchSummary.best_patch_ending_capital)}
                subtext="patch-audit sample"
                tone="cyan"
              />
              <MetricCard
                label="Validation ending capital"
                value={formatMoney(frozenPatchValidationSummary.validation_ending_capital)}
                subtext={`${String(frozenPatchValidationSummary.validation_window_count ?? 0)} validation windows`}
                tone="green"
              />
              <MetricCard
                label="Pass / fail windows"
                value={`${String(frozenPatchValidationSummary.year_window_pass_count ?? 0)} / ${String(frozenPatchValidationSummary.year_window_fail_count ?? 0)}`}
                subtext="year-by-year labels"
                tone="cyan"
              />
              <MetricCard
                label="Worst validation DD"
                value={formatPct(frozenPatchValidationSummary.max_validation_drawdown)}
                subtext={String(frozenPatchValidationSummary.worst_validation_window ?? "n/a")}
                tone="orange"
              />
              <MetricCard
                label="Walk-forward pass rate"
                value={formatPct(frozenPatchValidationSummary.walk_forward_pass_rate)}
                subtext={String(frozenPatchPromotionGate.classification ?? "n/a")}
                tone="cyan"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Best validation window"
                value={String(frozenPatchValidationSummary.best_validation_window ?? "n/a")}
                subtext={String(frozenPatchValidationSummary.recommended_next_action ?? "n/a")}
                tone="green"
              />
              <MetricCard
                label="Worst validation window"
                value={String(frozenPatchValidationSummary.worst_validation_window ?? "n/a")}
                subtext={String(frozenPatchValidationSummary.patch_appears_overfit ? "overfit risk flagged" : "overfit risk not dominant")}
                tone="orange"
              />
              <MetricCard
                label="Moonshot dependency"
                value={String(frozenPatchValidationSummary.moonshot_dependency_in_validation ?? "n/a")}
                subtext={`sans moonshots ${formatMoney(frozenPatchValidationSummary.profit_without_moonshots_in_validation)}`}
                tone="cyan"
              />
              <MetricCard
                label="Promotion gate"
                value={String(frozenPatchValidationSummary.promotion_gate_classification ?? "n/a")}
                subtext="read-only research gate"
                tone="orange"
              />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Frozen rules" title="Candidate and gate truth" className="p-0">
                <div className="space-y-3 px-5 py-5 text-sm text-white/68">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Promotion gate classification</div>
                    <div className="mt-2 text-lg font-semibold text-cyan-100">{String(frozenPatchPromotionGate.classification ?? "n/a")}</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 leading-7">
                    Validation ending capital: {formatMoney(frozenPatchValidationSummary.validation_ending_capital)}<br />
                    Walk-forward pass rate: {formatPct(frozenPatchValidationSummary.walk_forward_pass_rate)}<br />
                    True unseen proof available: {String(frozenPatchPromotionGate.true_unseen_proof_available ?? false)}
                  </div>
                  <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 leading-7 text-orange-100">
                    Diagnostic-only validation. No live, paper, runtime, allocator, or config mutation is exposed here.
                  </div>
                </div>
              </Section>

              <Section eyebrow="Validation scoreboard" title="Year and window outcomes" className="p-0">
                {frozenPatchYearRows.length || frozenPatchValidationWindows.length ? (
                  <div className="overflow-x-auto px-5 py-5">
                    <table className="min-w-full text-left text-sm">
                      <thead className="text-white/45">
                        <tr>
                          <th className="pb-3 pr-4 font-medium">Window</th>
                          <th className="pb-3 pr-4 font-medium">Trades</th>
                          <th className="pb-3 pr-4 font-medium">End cap</th>
                          <th className="pb-3 pr-4 font-medium">PF</th>
                          <th className="pb-3 pr-4 font-medium">Max DD</th>
                          <th className="pb-3 pr-4 font-medium">Label</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...frozenPatchValidationWindows, ...frozenPatchYearRows.slice(0, 6)].map((row, index) => (
                          <tr key={`${row.window_name ?? index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{row.window_name ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{formatMoney(row.ending_capital_from_20000)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.profit_factor ?? 0).toFixed(2)}</td>
                            <td className="py-3 pr-4 text-white/68">{formatPct(row.max_drawdown_pct)}</td>
                            <td className="py-3 pr-4 text-white/68">{row.validation_label ?? "n/a"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No frozen patch multi-year validation audit has been generated yet." />
                )}
              </Section>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No frozen patch multi-year validation audit found yet"
            body="Once `frozen_patch_validation_audit_001` exists, this section will show frozen-patch window proofs, walk-forward pass rate, moonshot dependency in validation, and the promotion-gate classification."
          />
        )}
      </Section>

      <Section eyebrow="Frozen Patch Forensic Integrity Audit" title="Proof Quality / Sample Reuse / Next Replay" source="structural_compounding_lab/output/frozen_patch_forensic_integrity_audit_001/">
        {Object.keys(frozenPatchForensicSummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Current proof status"
                value={String(frozenPatchForensicSummary.current_proof_status_label ?? "n/a")}
                subtext="read-only integrity classification"
                tone="orange"
              />
              <MetricCard
                label="Available data years"
                value={String((frozenPatchForensicSummary.available_source_years ?? []).join(", ") || "n/a")}
                subtext={`trade years ${(frozenPatchForensicSummary.available_trade_years ?? []).join(", ") || "n/a"}`}
                tone="cyan"
              />
              <MetricCard
                label="Trade artifact date range"
                value={String(frozenPatchForensicSummary.trade_artifact_date_range?.start ?? "n/a")}
                subtext={String(frozenPatchForensicSummary.trade_artifact_date_range?.end ?? "n/a")}
                tone="green"
              />
              <MetricCard
                label="True unseen proof"
                value={String(frozenPatchForensicSummary.true_unseen_proof_available ?? false)}
                subtext="current truthful answer"
                tone="orange"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Sample reuse risk"
                value={String(frozenPatchForensicSummary.sample_reuse_risk ?? "n/a")}
                subtext={String(frozenPatchForensicSampleReuse.current_validation_is_retrospective_only ? "retrospective only" : "independent sample")}
                tone="orange"
              />
              <MetricCard
                label="Leakage / overfit risk"
                value={String(frozenPatchForensicSummary.leakage_overfit_risk ?? frozenPatchForensicLeakage.risk_level ?? "n/a")}
                subtext={String(frozenPatchForensicLeakage.validation_windows_effectively_independent ? "independent windows" : "same-sample windows")}
                tone="orange"
              />
              <MetricCard
                label="Next required validation"
                value={String(frozenPatchForensicSummary.next_required_validation ?? "n/a")}
                subtext="exact replay still missing"
                tone="cyan"
              />
              <MetricCard
                label="Promotion blocker count"
                value={String(frozenPatchForensicSummary.promotion_blocker_count ?? frozenPatchForensicNoGoRisks.promotion_blocker_count ?? 0)}
                subtext="research-only blockers"
                tone="orange"
              />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Integrity truth" title="Lineage / Coverage / Gap" className="p-0">
                <div className="space-y-3 px-5 py-5 text-sm text-white/68">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 leading-7">
                    Same-sample validation detected: {String(frozenPatchForensicLineage.same_trade_artifact_used_for_discovery_and_validation ?? "n/a")}<br />
                    Raw source history sufficient to regenerate: {String(frozenPatchForensicCoverage.raw_source_history_sufficient_to_regenerate ?? "n/a")}<br />
                    Coverage sufficient for multi-year validation now: {String(frozenPatchForensicCoverage.coverage_is_sufficient_for_multi_year_validation ?? "n/a")}
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">What is proven</div>
                    <div className="mt-2 space-y-2">
                      {(frozenPatchForensicSummary.what_is_proven ?? []).slice(0, 3).map((item: string, index: number) => (
                        <div key={`${item}-${index}`} className="text-sm leading-6 text-white/66">
                          {item}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 leading-7 text-orange-100">
                    {String(frozenPatchForensicGap.why_1m_target_is_not_yet_proven ?? "This audit remains research-only and does not mutate paper/live/runtime behavior.")}
                  </div>
                </div>
              </Section>

              <Section eyebrow="Blockers and next replay" title="No-Go Risks" className="p-0">
                {(frozenPatchForensicNoGoRisks.blockers ?? []).length ? (
                  <div className="space-y-3 px-5 py-5">
                    {(frozenPatchForensicNoGoRisks.blockers ?? []).map((item: string, index: number) => (
                      <div
                        key={`${item}-${index}`}
                        className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 text-sm text-orange-100"
                      >
                        {item}
                      </div>
                    ))}
                    <div className="rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-4 py-3 text-sm leading-7 text-cyan-100">
                      {String(
                        frozenPatchForensicGap.minimum_next_validation_needed
                        ?? frozenPatchForensicSummary.next_required_validation
                        ?? frozenPatchForensicNextReplay.stage_1_generate_broad_historical_structural_outputs?.purpose
                        ?? "No next replay plan written yet.",
                      )}
                    </div>
                  </div>
                ) : (
                  <TableEmpty message="No frozen patch forensic integrity audit has been generated yet." />
                )}
              </Section>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No frozen patch forensic integrity audit found yet"
            body="Once `frozen_patch_forensic_integrity_audit_001` exists, this section will show the true proof boundary: sample reuse, available data years, lineage truth, and the exact replay still required before promotion."
          />
        )}
      </Section>

      <Section eyebrow="Broad Historical Structural Replay" title="Raw BTC To Regenerated Multi-Year Ledger" source="structural_compounding_lab/output/broad_historical_structural_replay_001/">
        {Object.keys(broadHistoricalReplaySummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                label="Source data range"
                value={String(broadHistoricalReplayCoverage.source_data_start ?? "n/a")}
                subtext={String(broadHistoricalReplayCoverage.source_data_end ?? "n/a")}
                tone="cyan"
              />
              <MetricCard
                label="Generated ledger range"
                value={String(broadHistoricalReplaySummary.generated_ledger_start ?? "n/a")}
                subtext={String(broadHistoricalReplaySummary.generated_ledger_end ?? "n/a")}
                tone="green"
              />
              <MetricCard
                label="Years generated"
                value={String((broadHistoricalReplaySummary.years_generated ?? []).join(", ") || "n/a")}
                subtext={`${String((broadHistoricalReplayHealth.generated_trade_years ?? []).length)} trade years`}
                tone="cyan"
              />
              <MetricCard
                label="Trades generated"
                value={String(broadHistoricalReplaySummary.trade_count ?? 0)}
                subtext={`L ${String(broadHistoricalReplaySummary.long_trade_count ?? 0)} / S ${String(broadHistoricalReplaySummary.short_trade_count ?? 0)}`}
                tone="green"
              />
              <MetricCard
                label="Next required step"
                value={String(broadHistoricalReplaySummary.next_required_step ?? "n/a")}
                subtext="read-only replay gate"
                tone="orange"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Replay health"
                value={broadHistoricalReplayHealth.successful_replay ? "healthy" : "attention"}
                subtext={`${String((broadHistoricalReplayHealth.zero_trade_windows ?? []).length)} zero-trade windows`}
                tone={broadHistoricalReplayHealth.successful_replay ? "green" : "orange"}
              />
              <MetricCard
                label="Safe for frozen patch validation"
                value={String(broadHistoricalReplayHealth.safe_for_frozen_patch_validation ?? broadHistoricalReplaySummary.coverage_sufficient_for_frozen_patch_validation ?? false)}
                subtext={`${String(broadHistoricalReplayLeakage.counts?.failed ?? 0)} leakage failures`}
                tone={(broadHistoricalReplayHealth.safe_for_frozen_patch_validation ?? broadHistoricalReplaySummary.coverage_sufficient_for_frozen_patch_validation) ? "green" : "orange"}
              />
              <MetricCard
                label="Missing minute count"
                value={String(broadHistoricalReplayCoverage.missing_timestamp_count ?? 0)}
                subtext={`${String(broadHistoricalReplayCoverage.duplicate_timestamp_count ?? 0)} duplicates removed`}
                tone="cyan"
              />
              <MetricCard
                label="Short-window untouched"
                value={String(broadHistoricalReplayManifest.current_short_window_artifacts_untouched ?? "n/a")}
                subtext={String(broadHistoricalReplayManifest.broad_replay_isolated ? "isolated output root" : "review isolation")}
                tone={broadHistoricalReplayManifest.current_short_window_artifacts_untouched ? "green" : "orange"}
              />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Manifest" title="Window and leakage truth" className="p-0">
                <div className="space-y-3 px-5 py-5 text-sm text-white/68">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 leading-7">
                    Source file: {String(broadHistoricalReplayCoverage.source_path ?? "n/a")}<br />
                    Cleaned rows: {String(broadHistoricalReplayCoverage.cleaned_rows ?? 0)}<br />
                    Zero-trade windows: {String((broadHistoricalReplayHealth.zero_trade_windows ?? []).join(", ") || "none")}<br />
                    Leakage unknown/manual-review checks: {String(broadHistoricalReplayLeakage.counts?.unknown ?? 0)}
                  </div>
                  <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 leading-7 text-orange-100">
                    Read-only research telemetry only. No strategy, paper, live, allocator, or config behavior is exposed for mutation here.
                  </div>
                </div>
              </Section>

              <Section eyebrow="Window counts" title="Year-by-year trade generation" className="p-0">
                {(broadHistoricalReplay?.yearly_trade_counts ?? []).length ? (
                  <div className="overflow-x-auto px-5 py-5">
                    <table className="min-w-full text-left text-sm">
                      <thead className="text-white/45">
                        <tr>
                          <th className="pb-3 pr-4 font-medium">Year</th>
                          <th className="pb-3 pr-4 font-medium">Trades</th>
                          <th className="pb-3 pr-4 font-medium">Long</th>
                          <th className="pb-3 pr-4 font-medium">Short</th>
                          <th className="pb-3 pr-4 font-medium">Setups</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(broadHistoricalReplay?.yearly_trade_counts ?? []).map((row, index) => (
                          <tr key={`${row.period ?? index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{row.period ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.long_trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.short_trade_count ?? "0"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.setup_count ?? "0"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No broad historical replay artifacts have been generated yet." />
                )}
              </Section>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No broad historical replay generated yet"
            body="Once `broad_historical_structural_replay_001` exists, this section will show the raw BTC source range, the regenerated ledger range, yearly trade counts, leakage-audit status, and whether the isolated multi-year ledger is ready for unchanged frozen-patch validation."
          />
        )}
      </Section>

      <Section eyebrow="Broad Frozen Patch Validation" title="Unchanged Patch Applied To The Broad Ledger" source="structural_compounding_lab/output/broad_frozen_patch_validation_001/">
        {Object.keys(broadFrozenPatchSummary).length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard
                label="Raw broad ending equity"
                value={formatMoney(broadFrozenPatchSummary.raw_broad_ending_equity)}
                subtext="completed structural replay ledger"
                tone="cyan"
              />
              <MetricCard
                label="Patched ending equity"
                value={formatMoney(broadFrozenPatchSummary.patched_broad_ending_equity)}
                subtext="frozen filtered-trade replay proxy"
                tone="green"
              />
              <MetricCard
                label="PF raw vs patch"
                value={`${Number(broadFrozenPatchSummary.raw_broad_profit_factor ?? 0).toFixed(2)} -> ${Number(broadFrozenPatchSummary.patched_broad_profit_factor ?? 0).toFixed(2)}`}
                subtext={`DD ${formatPct(broadFrozenPatchSummary.raw_broad_max_drawdown_pct)} -> ${formatPct(broadFrozenPatchSummary.patched_broad_max_drawdown_pct)}`}
                tone="orange"
              />
              <MetricCard
                label="Trades raw vs patch"
                value={`${String(broadFrozenPatchSummary.raw_broad_trade_count ?? 0)} -> ${String(broadFrozenPatchSummary.patched_broad_trade_count ?? 0)}`}
                subtext={`removed ${String(broadFrozenPatchSummary.removed_trade_count ?? 0)}`}
                tone="green"
              />
              <MetricCard
                label="Final classification"
                value={String(broadFrozenPatchSummary.final_patch_classification ?? "n/a")}
                subtext={String(broadFrozenPatchSummary.next_recommended_step ?? "research-only")}
                tone="orange"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Long R removed"
                value={String(Number(broadFrozenPatchSummary.long_R_removed ?? 0).toFixed(2))}
                subtext="damage stripped by frozen rule"
                tone="orange"
              />
              <MetricCard
                label="Short R preserved"
                value={String(Number(broadFrozenPatchSummary.short_R_preserved ?? 0).toFixed(2))}
                subtext="broad short edge kept"
                tone="green"
              />
              <MetricCard
                label="Moonshot verdict"
                value={String(broadFrozenPatchSummary.moonshot_dependency_verdict ?? broadFrozenPatchMoonshot?.patched?.classification ?? "n/a")}
                subtext="dependency truth"
                tone="cyan"
              />
              <MetricCard
                label="Execution-cost verdict"
                value={String(broadFrozenPatchSummary.execution_cost_verdict ?? "n/a")}
                subtext={`${String((broadFrozenPatchExecution.scenarios?.low_cost?.patch_improves_cost_survival ?? false) ? "low-cost improved" : "low-cost still weak")}`}
                tone="orange"
              />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
              <Section eyebrow="Year-by-year truth" title="Did the patch help or hurt?" className="p-0">
                {broadFrozenPatchYearly.length ? (
                  <div className="overflow-x-auto px-5 py-5">
                    <table className="min-w-full text-left text-sm">
                      <thead className="text-white/45">
                        <tr>
                          <th className="pb-3 pr-4 font-medium">Year</th>
                          <th className="pb-3 pr-4 font-medium">Raw PnL</th>
                          <th className="pb-3 pr-4 font-medium">Patch PnL</th>
                          <th className="pb-3 pr-4 font-medium">Raw PF</th>
                          <th className="pb-3 pr-4 font-medium">Patch PF</th>
                          <th className="pb-3 pr-4 font-medium">Verdict</th>
                        </tr>
                      </thead>
                      <tbody>
                        {broadFrozenPatchYearly.slice(0, 9).map((row, index) => (
                          <tr key={`${row.year ?? index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{row.year ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{formatMoney(row.raw_pnl)}</td>
                            <td className="py-3 pr-4 text-white/68">{formatMoney(row.patched_pnl)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.raw_profit_factor ?? 0).toFixed(2)}</td>
                            <td className="py-3 pr-4 text-white/68">{Number(row.patched_profit_factor ?? 0).toFixed(2)}</td>
                            <td className="py-3 pr-4 text-white/68">{row.patch_helped_or_hurt ?? "n/a"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No broad frozen patch validation has been generated yet." />
                )}
              </Section>

              <Section eyebrow="Forensic verdict" title="Risks / cost survival / next step" className="p-0">
                <div className="space-y-3 px-5 py-5 text-sm text-white/68">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 leading-7">
                    Years helped: {String(broadFrozenPatchSummary.yearly_verdict?.years_helped ?? broadFrozenPatchValidation?.patch_survival_by_year?.years_helped ?? 0)}<br />
                    Years hurt: {String(broadFrozenPatchSummary.yearly_verdict?.years_hurt ?? broadFrozenPatchValidation?.patch_survival_by_year?.years_hurt ?? 0)}<br />
                    Consistency: {String(broadFrozenPatchSummary.yearly_verdict?.yearly_consistency_label ?? broadFrozenPatchValidation?.patch_survival_by_year?.yearly_consistency_label ?? "n/a")}
                  </div>
                  <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 leading-7 text-orange-100">
                    {String(
                      broadFrozenPatchValidation?.next_research_recommendation?.next_step
                      ?? broadFrozenPatchSummary.next_recommended_step
                      ?? "No next step written yet.",
                    )}
                  </div>
                  {(broadFrozenPatchNoGo.blockers ?? []).length ? (
                    <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 text-orange-100">
                      Blockers: {(broadFrozenPatchNoGo.blockers ?? []).join(", ")}
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-emerald-400/18 bg-emerald-400/10 px-4 py-3 text-emerald-100">
                      No explicit no-go blockers were written into the artifact.
                    </div>
                  )}
                  <div className="rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-4 py-3 text-cyan-100">
                    Read-only research telemetry only. This section does not mutate runtime, config, live, or paper state.
                  </div>
                </div>
              </Section>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No broad frozen patch validation generated yet"
            body="Once `broad_frozen_patch_validation_001` exists, this section will show the unchanged patch applied to the completed broad ledger, the raw-vs-patch yearly verdict, moonshot dependency, cost survival, and the final research-only classification."
          />
        )}
      </Section>

      <Section eyebrow="Daily Opportunity Engine" title="BTC Structural Opportunity Truth" source="structural_compounding_lab/output/daily_structural_opportunity_001/ or latest preferred daily opportunity artifact">
        {dailyOpportunityRows.length ? (
          <div className="grid gap-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard label="Days analyzed" value={String(dailyOpportunitySummary.days_analyzed ?? 0)} subtext={dailyOpportunityMetadata.classification ?? "research-only"} />
              <MetricCard label="Valid days" value={String(dailyOpportunitySummary.valid_opportunity_days ?? 0)} subtext="daily structural opportunities" tone="green" />
              <MetricCard label="Strong hills" value={String(dailyOpportunitySummary.strong_structural_hill_days ?? 0)} subtext="high-conviction market structure" tone="green" />
              <MetricCard
                label="Actual trades"
                value={String(dailyOpportunitySummary.actual_trade_frequency?.actual_trade_count ?? 0)}
                subtext={`${String(dailyOpportunitySummary.actual_trade_frequency?.actual_trade_days ?? 0)} active trade days`}
                tone="green"
              />
              <MetricCard label="Noise avoided" value={String(dailyOpportunitySummary.noise_chasing_avoided_count ?? 0)} subtext="tiny wiggles correctly ignored" />
            </div>

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <MetricCard label="No-opportunity days" value={String(dailyOpportunitySummary.no_opportunity_days ?? 0)} subtext="flat or unrewarding structure" />
              <MetricCard label="True missed high-R" value={String(dailyOpportunitySummary.missed_high_R_opportunity_count ?? 0)} subtext="qualified high-R days with no actual trade" tone="orange" />
              <MetricCard label="High-R probe days" value={String(dailyOpportunitySummary.high_R_probe_day_count ?? 0)} subtext="strong days intentionally kept probe-only" />
              <MetricCard label="Full-size" value={String(dailyOpportunitySummary.full_size_count ?? 0)} subtext="strongest participation days" tone="green" />
              <MetricCard label="Too-tight days" value={String(dailyOpportunitySummary.too_tight_day_count ?? 0)} subtext="good structure, weak participation" tone="orange" />
              <MetricCard label="Reject-invalid" value={String(dailyOpportunitySummary.reject_invalid_count ?? 0)} subtext="broken or impossible geometry" tone="orange" />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
              <Section eyebrow="Top opportunity by day" title="Daily Structural Opportunity Tape" className="p-0">
                <div className="overflow-x-auto px-5 py-5">
                  <table className="min-w-full text-left text-sm">
                    <thead className="text-white/45">
                      <tr>
                        <th className="pb-3 pr-4 font-medium">Date</th>
                        <th className="pb-3 pr-4 font-medium">Side</th>
                        <th className="pb-3 pr-4 font-medium">Label</th>
                        <th className="pb-3 pr-4 font-medium">Score</th>
                        <th className="pb-3 pr-4 font-medium">Archetype</th>
                        <th className="pb-3 pr-4 font-medium">Personality</th>
                        <th className="pb-3 pr-4 font-medium">Participation</th>
                        <th className="pb-3 pr-4 font-medium">Actual Trades</th>
                        <th className="pb-3 pr-4 font-medium">Opened Setups</th>
                        <th className="pb-3 pr-4 font-medium">Expected R</th>
                        <th className="pb-3 pr-4 font-medium">High-R Audit</th>
                        <th className="pb-3 pr-4 font-medium">Room</th>
                        <th className="pb-3 pr-4 font-medium">Danger</th>
                        <th className="pb-3 pr-4 font-medium">Explanation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {dailyOpportunityRows.slice(0, 40).map((row, index) => (
                        <tr key={`${row.date ?? row.timestamp ?? index}`} className="border-t border-white/6 align-top">
                          <td className="py-3 pr-4 text-white/68">{row.date ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.side ?? "flat"}</td>
                          <td className="py-3 pr-4 font-medium text-white">{row.opportunity_label ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{Number(row.opportunity_score ?? 0).toFixed(1)}</td>
                          <td className="py-3 pr-4 text-white/68">{row.best_archetype ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.best_personality ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.participation_mode ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.actual_trade_count ?? "0"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.opened_setup_count ?? "0"}</td>
                          <td className="py-3 pr-4 text-white/68">{Number(row.expected_R_potential ?? 0).toFixed(2)}</td>
                          <td className="py-3 pr-4 text-white/68">{row.missed_high_r_audit_category ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{Number(row.room_to_target_score ?? 0).toFixed(2)}</td>
                          <td className="py-3 pr-4 text-white/68">{Number(row.danger_score ?? 0).toFixed(2)}</td>
                          <td className="py-3 pr-4 text-white/55">{row.explanation ?? "n/a"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>

              <div className="grid gap-5">
                <Section eyebrow="Support / resistance intelligence" title="Zone Quality / Breakout / Retest">
                  <div className="grid gap-3">
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      breakout-retest hold days: <span className="font-medium text-white">{String(dailyOpportunity?.sr_zone_report?.breakout_retest_hold_days ?? 0)}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      failed breakout days: <span className="font-medium text-white">{String(dailyOpportunity?.sr_zone_report?.failed_breakout_days ?? 0)}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      average zone quality: <span className="font-medium text-white">{Number(dailyOpportunity?.sr_zone_report?.average_zone_quality_score ?? 0).toFixed(2)}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      source updated: <span className="font-medium text-white">{formatTime(dailyOpportunityMetadata.last_updated)}</span>
                    </div>
                  </div>
                </Section>

                <Section eyebrow="Too tight vs wiggle chasing" title="Participation Guardrails">
                  <div className="grid gap-3">
                    <div className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3 text-sm text-orange-100">
                      too-tight days: {String(dailyOpportunitySummary.too_tight_day_count ?? 0)} | missed valid: {String(dailyOpportunitySummary.missed_valid_opportunity_count ?? 0)}
                    </div>
                    <div className="rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-4 py-3 text-sm text-cyan-100">
                      noise-chasing avoided: {String(dailyOpportunitySummary.noise_chasing_avoided_count ?? 0)} | tiny wiggles: {String(dailyOpportunity?.noise_chasing_report?.tiny_wiggle_flag_count ?? 0)}
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      next step: <span className="font-medium text-white">{dailyOpportunity?.next_research_recommendation?.next_step ?? "n/a"}</span>
                    </div>
                    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/68">
                      read-only source files: <span className="font-medium text-white">{String((dailyOpportunityMetadata.source_files ?? []).length)}</span>
                    </div>
                  </div>
                </Section>
              </div>
            </div>
          </div>
        ) : (
          <EmptyState
            title="No daily structural opportunity artifact found yet"
            body="Once `daily_structural_opportunity_001` exists, this section will show day-level structural opportunity labels, participation routing, support/resistance intelligence, and the too-tight versus wiggle-chasing balance."
          />
        )}
      </Section>

      <Section eyebrow="Operator truth" title="Artifact Freshness And Empty-State Honesty" source="Resolved artifact map from common/dashboard_telemetry.py">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {latestArtifacts.map(([key, status]) => (
            <div key={key} className={clsx("rounded-2xl border px-4 py-3", toneForArtifact(String(status.status ?? "")))}>
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/55">{key}</div>
              <div className="mt-2 text-sm break-all">{String(status.path ?? "n/a")}</div>
              <div className="mt-3 text-xs text-white/60">
                {status.exists ? `updated ${formatTime(status.last_modified_timestamp)}` : "artifact missing"}
              </div>
            </div>
          ))}
        </div>
      </Section>
        </>
      ) : null}
    </div>
  );

  const marketReplayContent = (
    <div className="grid gap-5">
      {data?.lab?.has_run ? null : (
        <Section eyebrow="Replay truth" title="Structural Replay Is Scaffolded, Not Fabricated">
          <EmptyState
            title="No structural backtest run found yet"
            body="The replay theatre is already wired for candles, EMA overlays, trade markers, condition cards, fullscreen charting, and future structure overlays. Once the external structural-lab project writes its output artifacts, this page will light up without touching the active paper or backtest cockpit."
          />
        </Section>
      )}

      <Section eyebrow="Replay controls" title="Symbol / Timeframe" source={shadowCanonicalPath}>
        <div className="flex flex-wrap gap-3">
          <label className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/72">
            Symbol
            <select
              className="ml-3 bg-transparent text-white outline-none"
              value={selectedSymbol}
              onChange={(event) => setSymbol(event.target.value)}
            >
              {availableSymbols.map((item) => (
                <option key={item} value={item} className="bg-slate-950 text-white">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <label className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/72">
            Timeframe
            <select
              className="ml-3 bg-transparent text-white outline-none"
              value={selectedTimeframe}
              onChange={(event) => setTimeframe(event.target.value)}
            >
              {availableTimeframes.map((item) => (
                <option key={item} value={item} className="bg-slate-950 text-white">
                  {item}
                </option>
              ))}
            </select>
          </label>
          <div className="rounded-full border border-cyan-300/16 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-100">
            Shadow-forward tape with dashboard-only public visual extension. No runtime mutation, no real money, no paper integration.
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {timeframeOptions.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setTimeframe(item)}
              className={clsx(
                "rounded-full border px-4 py-2 text-xs uppercase tracking-[0.22em] transition",
                selectedTimeframe === item
                  ? "border-cyan-300/32 bg-cyan-400/14 text-cyan-50"
                  : "border-white/10 bg-white/5 text-white/62 hover:border-cyan-300/18 hover:text-white",
              )}
            >
              {item}
            </button>
          ))}
        </div>
      </Section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Canonical rows" value={String(shadowCanonical.row_count ?? 0)} subtext="closed 1m shadow-forward candles" tone="green" />
        <MetricCard label="Runtime decisions" value={String(shadowDecisions.total_decisions ?? 0)} subtext={`${String(shadowDecisions.processed_this_run ?? 0)} processed last run`} />
        <MetricCard label="Runtime trades" value={String(shadowTrades.total_simulated_trades ?? 0)} subtext="research observations only" tone="orange" />
        <MetricCard label="Artifact trades" value={String(tradeRows.length)} subtext="legacy structural replay markers" />
      </div>

      <CandlePanel
        apiUrl={API_URL}
        endpointPath="/api/structural-lab/candles"
        panelLabel={`Primary Shadow Forward Live Visual Chart / ${selectedTimeframe}`}
        symbol={selectedSymbol}
        timeframe={selectedTimeframe}
        mode="structural_lab"
      />

      <div className="grid gap-5 xl:grid-cols-3">
        <Section eyebrow="Condition card" title="Replay Context" source={`${decisionLedgerPath} + legacy structural setup/trade artifacts`}>
          <div className="space-y-3 text-sm text-white/68">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              Support, resistance, liquidity sweeps, add-ons, profit-lock events, and cooldown markers are drawn from structural artifacts instead of mocked UI placeholders.
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              Latest structural trade: {latestTrade ? `${latestTrade.symbol ?? selectedSymbol} / ${latestTrade.side ?? "n/a"} / ${latestTrade.exit_reason ?? "open"}` : "No trades available"}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              Latest setup review: {latestSetup ? `${latestSetup.symbol ?? selectedSymbol} / ${latestSetup.classification ?? latestSetup.setup_class ?? "n/a"} / score ${Number(latestSetup.total_score ?? latestSetup.score ?? 0).toFixed(2)}` : "No setups available"}
            </div>
          </div>
        </Section>
        <Section eyebrow="Vault state" title="Historical Convexity / Lock / Cooldown" source="structural_compounding_lab/output/profit_vault.json + cooldown/pyramiding logs">
          <div className="space-y-3 text-sm text-white/68">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              Cycle {overview?.current_compounding_cycle ?? "cycle-0"} | locked {formatMoney(overview?.locked_profit)} | active {formatMoney(overview?.active_trading_capital)}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              Latest cooldown event: {latestCooldownEvent ? `${formatTime(latestCooldownEvent.timestamp)} | ${latestCooldownEvent.reason ?? latestCooldownEvent.event_type ?? "cooldown"}` : "No cooldown events yet"}
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              Latest convex event: {latestPyramidingEvent ? `${formatTime(latestPyramidingEvent.timestamp)} | ${latestPyramidingEvent.add_type ?? latestPyramidingEvent.event_type ?? "pyramid"}` : "No add-on or profit-lock event yet"}
            </div>
          </div>
        </Section>
        <Section eyebrow="Replay counters" title="Market-Theatre Coverage" source="legacy structural overlay logs: level_log, liquidity_events, cooldown_log">
          <div className="grid gap-3">
            <MetricCard label="Cooldown rows" value={String(cooldownRows.length)} subtext={`Releases ${String(overview?.cooldown_release_count ?? 0)}`} tone="orange" />
            <MetricCard label="Liquidity events" value={String(liquidityRows.length)} subtext="Sweeps, failed breaks, and reclaims" />
            <MetricCard label="Levels" value={String(levelRows.length)} subtext="Range, previous-period, and pivot structure" tone="green" />
          </div>
        </Section>
      </div>
    </div>
  );

  const structureMapContent = (
    <div className="grid gap-5">
      {!data || !multiSymbolResults.length ? (
        <Section eyebrow="Loading active forward runtime" title="Waiting For Multi-Symbol Runtime Snapshot">
          <div className="rounded-[24px] border border-cyan-300/16 bg-cyan-400/10 px-4 py-4 text-sm leading-7 text-cyan-50/82">
            Structure will render after `multi_symbol_forward_runtime_earned_parallel_slots/latest_status.json` is loaded.
            It will not show historical `level_log.csv` or `liquidity_events.csv` as active forward data.
          </div>
        </Section>
      ) : null}
      {data && multiSymbolResults.length ? (
      <Section
        eyebrow="Active six-month forward structure"
        title="Runtime Timeframe Formation And Data Quality"
        source={String(multiSymbolDecisions.runtime_root ?? "structural_compounding_lab/output/multi_symbol_forward_runtime_earned_parallel_slots")}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Runtime status"
            value={String(multiSymbolRuntime.status_color ?? "n/a")}
            subtext={`${String(multiSymbolRuntime.symbols_clean ?? 0)} / ${String(multiSymbolRuntime.symbols_checked ?? 0)} active symbols clean`}
            tone={multiRuntimeIsGreen ? "green" : "orange"}
          />
          <MetricCard
            label="Latest closed 1m"
            value={formatTime(multiSymbolRuntime.latest_safe_1m_timestamp)}
            subtext={`${String(multiSymbolRuntime.total_appended_rows ?? 0)} rows appended last run`}
            tone="cyan"
          />
          <MetricCard
            label="Decision slots"
            value={String(multiSymbolDecisions.total_decision_slots ?? 0)}
            subtext={`new ${String(multiSymbolRuntime.total_new_decision_rows ?? 0)} / duplicate keys ${String(multiSymbolRuntime.decision_ledger_duplicate_keys ?? 0)}`}
            tone={Number(multiSymbolRuntime.decision_ledger_duplicate_keys ?? 1) === 0 ? "green" : "orange"}
          />
          <MetricCard
            label="Historical tables"
            value="HIDDEN"
            subtext="level_log/liquidity_events are research archive only"
            tone="green"
          />
        </div>

        <div className="mt-5 overflow-x-auto rounded-[24px] border border-white/10 bg-white/5">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-white/8 text-white/45">
              <tr>
                <th className="px-4 py-3 font-medium">Symbol</th>
                <th className="px-4 py-3 font-medium">Latest 1m</th>
                <th className="px-4 py-3 font-medium">Rows</th>
                <th className="px-4 py-3 font-medium">15m bars</th>
                <th className="px-4 py-3 font-medium">1H bars</th>
                <th className="px-4 py-3 font-medium">Gaps / Dupes / OHLC</th>
                <th className="px-4 py-3 font-medium">Fetch</th>
              </tr>
            </thead>
            <tbody>
              {multiSymbolResults.map((row) => {
                const quality = row.quality ?? {};
                const clean = Boolean(quality.clean);
                return (
                  <tr key={String(row.symbol ?? "symbol")} className="border-t border-white/6">
                    <td className="px-4 py-3 font-medium text-white">{String(row.symbol ?? "n/a")}</td>
                    <td className="px-4 py-3 text-white/72">{formatTime(row.latest_safe_1m_timestamp ?? quality.last_timestamp)}</td>
                    <td className="px-4 py-3 text-white/72">{String(row.rows_after ?? quality.rows ?? 0)}</td>
                    <td className="px-4 py-3 text-white/72">{String(row.complete_15m_bars ?? quality.complete_15m_bars ?? 0)}</td>
                    <td className="px-4 py-3 text-white/72">{String(row.complete_1h_bars ?? quality.complete_1h_bars ?? 0)}</td>
                    <td className={clsx("px-4 py-3 font-medium", clean ? "text-emerald-200" : "text-orange-200")}>
                      {String(quality.gap_count ?? 0)} / {String(quality.duplicate_count ?? 0)} / {String(quality.ohlc_failure_count ?? 0)}
                    </td>
                    <td className="px-4 py-3 text-white/72">
                      {row.fetch_attempted ? `${String(row.fetched_rows ?? 0)} rows` : "not attempted"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-4 rounded-[24px] border border-cyan-300/16 bg-cyan-400/10 px-4 py-4 text-sm leading-7 text-cyan-50/82">
          This tab is now forward-runtime only. Historical support/resistance and liquidity artifacts are not shown here
          because they come from legacy research output, not from the active six-month forward scheduler.
        </div>
      </Section>
      ) : null}

      <Section eyebrow="Research archive boundary" title="Historical Structure Tables Are Not Live Forward Evidence">
        <div className="grid gap-4 xl:grid-cols-[1fr_auto] xl:items-center">
          <p className="text-sm leading-7 text-white/66">
            The old `level_log.csv` and `liquidity_events.csv` files are preserved for forensic research, but they are
            deliberately hidden from the operational Structure tab so they cannot be confused with the current
            six-month forward run.
          </p>
          <button
            type="button"
            onClick={() => setShowResearchArchive((current) => !current)}
            className="holo-button rounded-2xl border border-cyan-300/24 bg-cyan-400/12 px-5 py-3 text-sm font-medium text-cyan-50"
          >
            {showResearchArchive ? "Hide historical structure archive" : "Show historical structure archive"}
          </button>
        </div>
        {showResearchArchive ? (
          <div className="mt-5 grid gap-5 xl:grid-cols-2">
            <div className="rounded-[24px] border border-orange-300/18 bg-orange-400/8 p-4">
              <div className="text-[10px] uppercase tracking-[0.28em] text-orange-100/80">Historical level_log.csv</div>
              <div className="mt-3 max-h-[420px] overflow-auto">
                {levelRows.length ? (
                  <table className="min-w-full text-left text-sm">
                    <tbody>
                      {levelRows.slice(-20).reverse().map((row, index) => (
                        <tr key={`${row.timestamp ?? row.first_seen ?? index}`} className="border-t border-white/6">
                          <td className="py-3 pr-4 text-white/68">{formatTime(row.timestamp ?? row.first_seen)}</td>
                          <td className="py-3 pr-4 font-medium text-white">{row.type ?? row.level_type ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.price ?? row.level_price ?? "n/a"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <TableEmpty message="No historical level rows available." />
                )}
              </div>
            </div>
            <div className="rounded-[24px] border border-orange-300/18 bg-orange-400/8 p-4">
              <div className="text-[10px] uppercase tracking-[0.28em] text-orange-100/80">Historical liquidity_events.csv</div>
              <div className="mt-3 max-h-[420px] overflow-auto">
                {liquidityRows.length ? (
                  <table className="min-w-full text-left text-sm">
                    <tbody>
                      {liquidityRows.slice(-20).reverse().map((row, index) => (
                        <tr key={`${row.timestamp ?? row.event_time ?? index}`} className="border-t border-white/6">
                          <td className="py-3 pr-4 text-white/68">{formatTime(row.timestamp ?? row.event_time)}</td>
                          <td className="py-3 pr-4 font-medium text-white">{row.type ?? row.event_type ?? "n/a"}</td>
                          <td className="py-3 pr-4 text-white/68">{row.price ?? "n/a"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <TableEmpty message="No historical liquidity rows available." />
                )}
              </div>
            </div>
          </div>
        ) : null}
      </Section>
    </div>
  );

  const profitVaultContent = (
    <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
      <div className="xl:col-span-2">
        <Section eyebrow="Research archive boundary" title="Research Vault Is Historical, Not Active Forward PnL">
          <div className="rounded-[24px] border border-orange-300/18 bg-orange-400/8 px-4 py-4 text-sm leading-7 text-orange-50/82">
            This tab intentionally contains historical/vault research artifacts. It is not the active six-month
            forward scheduler result. For the current forward run, use Command, Candles, Structure, and Trade Review.
          </div>
        </Section>
      </div>
      <Section eyebrow="Vault accounting" title="Historical Base / Active / Locked" source="structural_compounding_lab/output/profit_vault.json + structural_compounding_lab/output/summary.json">
        <div className="grid gap-4 md:grid-cols-2">
          <MetricCard label="Base capital" value={formatMoney(overview?.base_capital)} subtext="Static research base" />
          <MetricCard label="Locked profit" value={formatMoney(overview?.locked_profit)} subtext="Protected after danger" tone="orange" />
          <MetricCard label="Active trading capital" value={formatMoney(overview?.active_trading_capital)} subtext="Capital currently in cycle" tone="green" />
          <MetricCard label="Current equity" value={formatMoney(overview?.current_equity)} subtext={`Cooldown ${overview?.cooldown_state ?? "inactive"}`} />
        </div>
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/65">
          This vault stays read-only. The scaffold is designed to later show cycle-by-cycle profit locking, capital resets to base, cooldown activation, and eventual guarded re-entry once structure becomes favorable again.
        </div>
      </Section>

      <Section eyebrow="Vault event tape" title="Locks / Cooldowns / Resets" source="structural_compounding_lab/output/cooldown_log.csv + structural_compounding_lab/output/pyramiding_log.csv">
        {cooldownRows.length || pyramidingRows.length || data?.profit_vault ? (
          <div className="space-y-3">
            {cooldownRows.slice(-12).reverse().map((row, index) => (
              <div key={`${row.timestamp ?? row.cooldown_start ?? index}`} className="rounded-2xl border border-orange-400/18 bg-orange-400/10 px-4 py-3">
                <div className="text-[10px] uppercase tracking-[0.24em] text-orange-200/70">Cooldown</div>
                <div className="mt-2 text-sm text-orange-100">
                  {formatTime(row.timestamp ?? row.cooldown_start)} | {row.reason ?? "danger sniffer"}
                </div>
              </div>
            ))}
            {pyramidingRows.slice(-12).reverse().map((row, index) => (
              <div key={`${row.timestamp ?? row.event_time ?? index}`} className="rounded-2xl border border-cyan-400/18 bg-cyan-400/10 px-4 py-3">
                <div className="text-[10px] uppercase tracking-[0.24em] text-cyan-200/70">Pyramiding / Vault Event</div>
                <div className="mt-2 text-sm text-cyan-100">
                  {formatTime(row.timestamp ?? row.event_time)} | {row.add_type ?? row.event_type ?? "research event"}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <TableEmpty message="No profit vault state yet." />
        )}
      </Section>
    </div>
  );

  const tradeReviewContent = (
    <div className="grid gap-5">
      {!data ? (
        <Section eyebrow="Loading active forward runtime" title="Waiting For Trade/Decision Snapshot">
          <div className="rounded-[24px] border border-cyan-300/16 bg-cyan-400/10 px-4 py-4 text-sm leading-7 text-cyan-50/82">
            Trade Review will render after the active multi-symbol runtime status and decision ledger paths are loaded.
            It will not show historical `trades.csv` or `setup_log.csv` as active forward trades.
          </div>
        </Section>
      ) : null}
      {data ? (
      <Section
        eyebrow="Active six-month forward trade review"
        title="Forward Decision Slots, Trade Triggers And Email Truth"
        source={`${String(multiSymbolDecisions.ledger_path ?? "multi_symbol_forward_decision_ledger.csv")} + ${String(multiSymbolRuntime.multi_asset_trade_trigger_email_ledger ?? "trade event email ledger")}`}
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Decision slots"
            value={String(multiSymbolDecisions.total_decision_slots ?? 0)}
            subtext={`new this run ${String(multiSymbolRuntime.total_new_decision_rows ?? 0)}`}
            tone="cyan"
          />
          <MetricCard
            label="Trade triggers"
            value={String(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0)}
            subtext={`${String(multiSymbolRuntime.multi_asset_trade_trigger_emails_sent_this_run ?? 0)} emails sent this run`}
            tone={Number(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0) > 0 ? "orange" : "green"}
          />
          <MetricCard
            label="Duplicate keys"
            value={String(multiSymbolRuntime.decision_ledger_duplicate_keys ?? 0)}
            subtext="decision ledger idempotency"
            tone={Number(multiSymbolRuntime.decision_ledger_duplicate_keys ?? 1) === 0 ? "green" : "orange"}
          />
          <MetricCard
            label="Order path"
            value="OFF"
            subtext="research-only; no live/paper order path"
            tone="green"
          />
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 text-sm leading-7 text-white/68">
            <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Current forward trade state</div>
            <div className="mt-3 text-lg font-semibold text-white">
              {Number(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0) > 0
                ? "Trade event recorded this run"
                : "No trade event recorded this run"}
            </div>
            <div>Latest runtime candle: {formatTime(multiSymbolRuntime.latest_safe_1m_timestamp)}</div>
            <div className="break-words">Trade event email subject prefix: {String(multiSymbolRuntime.multi_asset_trade_trigger_email_subject_prefix ?? "n/a")}</div>
            <div className="grid gap-1">
              <span>Latest trade email draft</span>
              <span
                className="min-w-0 max-w-full truncate rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/58"
                title={String(multiSymbolRuntime.multi_asset_trade_trigger_latest_email ?? "n/a")}
              >
                {compactPath(multiSymbolRuntime.multi_asset_trade_trigger_latest_email ?? "n/a", 5)}
              </span>
            </div>
            <div className="mt-2 text-white/54">
              This is the active forward scheduler truth. Historical closed trades are not shown here unless you open the archive below.
            </div>
          </div>

          <div className="rounded-[24px] border border-emerald-300/18 bg-emerald-400/8 px-4 py-4 text-sm leading-7 text-white/68">
            <div className="text-[10px] uppercase tracking-[0.28em] text-emerald-200/72">Safety flags</div>
            <div className="mt-3 grid gap-2">
              <div>research_only: <span className="text-white">{String(multiSymbolRuntime.research_only ?? true)}</span></div>
              <div>paper_validation_ready: <span className="text-white">{String(multiSymbolRuntime.paper_validation_ready ?? false)}</span></div>
              <div>paper_allowed: <span className="text-white">{String(multiSymbolRuntime.paper_allowed ?? false)}</span></div>
              <div>live_allowed: <span className="text-white">{String(multiSymbolRuntime.live_allowed ?? false)}</span></div>
              <div>order_path_created: <span className="text-white">{String(multiSymbolRuntime.order_path_created ?? false)}</span></div>
              <div>broker_path_created: <span className="text-white">{String(multiSymbolRuntime.broker_path_created ?? false)}</span></div>
            </div>
          </div>
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-[24px] border border-cyan-300/16 bg-cyan-400/8 px-4 py-4">
            <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Wait-time context</div>
            <div className="mt-3 grid gap-3">
              <div className="flex justify-between gap-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
                <span className="text-white/58">Latest decision slot</span>
                <span className="text-right text-white">{formatTime(multiSymbolOperatorTape.latest_decision_slot)}</span>
              </div>
              <div className="flex justify-between gap-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
                <span className="text-white/58">Observed runtime span</span>
                <span className="text-white">{number(multiSymbolOperatorTape.observed_decision_span_hours ?? 0, 2)}h</span>
              </div>
              <div className="flex justify-between gap-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
                <span className="text-white/58">Historical median wait</span>
                <span className="text-white">{number(multiSymbolOperatorTape.historical_median_wait_after_exit_hours ?? 12, 2)}h</span>
              </div>
              <div className="flex justify-between gap-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm">
                <span className="text-white/58">Holdout median wait</span>
                <span className="text-white">{number(multiSymbolOperatorTape.holdout_median_wait_after_exit_hours ?? 10, 2)}h</span>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-4">
            <div className="text-[10px] uppercase tracking-[0.28em] text-cyan-200/72">Per-symbol latest decision tape</div>
            <div className="mt-3 max-h-[430px] overflow-auto">
              {operatorSymbolTape.length ? (
                <table className="min-w-full text-left text-sm">
                  <thead className="sticky top-0 border-b border-white/10 bg-slate-950/95 text-white/45">
                    <tr>
                      <th className="py-3 pr-4 font-medium">Symbol</th>
                      <th className="py-3 pr-4 font-medium">Latest slot</th>
                      <th className="py-3 pr-4 font-medium">1m rows</th>
                      <th className="py-3 pr-4 font-medium">Signal</th>
                      <th className="py-3 pr-4 font-medium">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {operatorSymbolTape.map((row, index) => (
                      <tr key={`${row.symbol ?? "symbol"}-${index}`} className="border-t border-white/6">
                        <td className="py-3 pr-4 font-semibold text-white">{String(row.symbol ?? "n/a")}</td>
                        <td className="py-3 pr-4 text-white/64">{formatTime(row.latest_decision_slot)}</td>
                        <td className="py-3 pr-4 text-white/64">{String(row.source_1m_count ?? 0)}</td>
                        <td className={clsx("py-3 pr-4 font-medium", row.strategy_signal_evaluated ? "text-emerald-200" : "text-white/42")}>
                          {row.strategy_signal_evaluated ? "evaluated" : "not evaluated"}
                        </td>
                        <td className="max-w-[420px] break-words py-3 pr-4 text-white/64">{String(row.latest_reason ?? "n/a")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <TableEmpty message="No per-symbol active decision tape rows yet." />
              )}
            </div>
          </div>
        </div>
      </Section>
      ) : null}

      <Section eyebrow="Research archive boundary" title="Historical Trade Tables Are Not Active Forward Trades">
        <div className="grid gap-4 xl:grid-cols-[1fr_auto] xl:items-center">
          <p className="text-sm leading-7 text-white/66">
            The old `trades.csv`, `setup_log.csv`, and trade-frequency PnL panels are historical research artifacts.
            They are preserved for audit, but hidden from the active Trade Review by default so the six-month forward
            run remains clean and honest.
          </p>
          <button
            type="button"
            onClick={() => setShowResearchArchive((current) => !current)}
            className="holo-button rounded-2xl border border-cyan-300/24 bg-cyan-400/12 px-5 py-3 text-sm font-medium text-cyan-50"
          >
            {showResearchArchive ? "Hide historical trade archive" : "Show historical trade archive"}
          </button>
        </div>

        {showResearchArchive ? (
          <div className="mt-5 grid gap-5">
            <TradeFrequencyPnlPanel
              payload={data?.trade_frequency_pnl}
              title="Historical Research Trading Activity KPIs"
              subtitle="Archived structural realized trade aggregation; not active forward PnL"
            />
            <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
              <div className="rounded-[24px] border border-orange-300/18 bg-orange-400/8 p-4">
                <div className="text-[10px] uppercase tracking-[0.28em] text-orange-100/80">Historical trades.csv</div>
                {tradeRows.length ? (
                  <div className="mt-3 max-h-[520px] overflow-auto">
                    <table className="min-w-full text-left text-sm">
                      <tbody>
                        {tradeRows.slice(-40).reverse().map((row, index) => (
                          <tr key={`${row.trade_id ?? row.entry_time ?? index}`} className="border-t border-white/6">
                            <td className="py-3 pr-4 font-medium text-white">{row.symbol ?? "BTCUSDT"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.side ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.r_multiple ?? row.pnl_r ?? "n/a"}</td>
                            <td className="py-3 pr-4 text-white/68">{row.exit_reason ?? "n/a"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <TableEmpty message="No historical trade rows available." />
                )}
              </div>
              <div className="rounded-[24px] border border-orange-300/18 bg-orange-400/8 p-4">
                <div className="text-[10px] uppercase tracking-[0.28em] text-orange-100/80">Historical setup_log.csv</div>
                {setupRows.length ? (
                  <div className="mt-3 max-h-[520px] overflow-auto space-y-3">
                    {setupRows.slice(-12).reverse().map((row, index) => (
                      <div key={`${row.timestamp ?? row.setup_time ?? index}`} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                        <div className="text-sm font-medium text-white">{row.symbol ?? selectedSymbol}</div>
                        <div className="mt-2 text-xs uppercase tracking-[0.2em] text-white/45">{formatTime(row.timestamp ?? row.setup_time)}</div>
                        <div className="mt-3 text-sm leading-6 text-white/64">
                          {row.explanation ?? row.entry_reason ?? "No setup explanation written."}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <TableEmpty message="No historical setup rows available." />
                )}
              </div>
            </div>
          </div>
        ) : null}
      </Section>
    </div>
  );

  const settingsContent = (
    <div className="grid gap-5 xl:grid-cols-2">
      <Section eyebrow="Read-only research config" title="Structural Settings" source="structural_compounding_lab/config/structural_compounding_settings.json">
        <JsonBlock value={data?.settings ?? {}} />
      </Section>
      <Section eyebrow="Universe and artifact roots" title="Symbols / Output / Report" source="common/structural_lab_locator.py resolved project root + structural_compounding_lab/output/">
        <div className="space-y-4">
          <JsonBlock value={data?.symbols_config ?? {}} />
          <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/65">
            <div className="text-[10px] uppercase tracking-[0.22em] text-white/48">Output root</div>
            <div className="mt-2 truncate" title={String(data?.lab?.output_path ?? "n/a")}>
              {compactPath(data?.lab?.output_path ?? "n/a", 5)}
            </div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-white/65">
            <div className="text-[10px] uppercase tracking-[0.22em] text-white/48">Report excerpt</div>
            <div className="mt-2 whitespace-pre-wrap leading-6">
              {data?.report_markdown ? data.report_markdown.split("\n").slice(0, 10).join("\n") : "No report.md found yet."}
            </div>
          </div>
        </div>
      </Section>
    </div>
  );

  const candlesWorkspaceContent = (
    <div className="grid gap-4">
      {!data ? (
        <section className="cinematic-card rounded-[30px] border border-cyan-300/16 bg-[linear-gradient(135deg,rgba(4,16,30,0.94),rgba(6,9,20,0.9))] p-6">
          <div className="text-[11px] uppercase tracking-[0.34em] text-cyan-100/70">Loading active runtime tape</div>
          <div className="mt-3 text-2xl font-semibold text-white">Waiting for dashboard artifacts…</div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-white/58">
            The chart will render only after the active multi-symbol runtime snapshot is available, so the page does not
            show a misleading BTC fallback while the API is still loading.
          </p>
        </section>
      ) : null}
      {data ? (
      <>
      <section className="cinematic-card relative overflow-hidden rounded-[30px] border border-cyan-300/16 bg-[linear-gradient(135deg,rgba(4,16,30,0.94),rgba(6,9,20,0.9))] p-4 shadow-[0_24px_90px_rgba(0,0,0,0.32)]">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-[11px] uppercase tracking-[0.34em] text-cyan-100/70">Active candle theatre</div>
              <span className={clsx(
                "rounded-full border px-3 py-1 text-[10px] uppercase tracking-[0.22em]",
                selectedSymbolUsesActiveRuntime
                  ? "border-emerald-300/24 bg-emerald-400/12 text-emerald-100"
                  : "border-orange-300/24 bg-orange-400/12 text-orange-100",
              )}>
                {selectedSymbolUsesActiveRuntime ? "active multi-symbol tape" : "fallback tape"}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-end gap-3">
              <h1 className="text-3xl font-semibold tracking-tight text-white">{selectedSymbol} / {selectedTimeframe}</h1>
              <span className="pb-1 text-sm text-white/54">
                closed candles + read-only public visual extension
              </span>
            </div>
          </div>

          <div className="grid min-w-[min(100%,560px)] grid-cols-3 gap-2">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
              <div className="text-[9px] uppercase tracking-[0.22em] text-white/42">latest 1m</div>
              <div className="mt-1 truncate text-sm font-semibold text-white">{formatTime(multiSymbolRuntime.latest_safe_1m_timestamp)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
              <div className="text-[9px] uppercase tracking-[0.22em] text-white/42">1H slots</div>
              <div className="mt-1 text-sm font-semibold text-white">{String(selectedSymbolRuntime?.complete_1h_bars ?? 0)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
              <div className="text-[9px] uppercase tracking-[0.22em] text-white/42">quality</div>
              <div className={clsx("mt-1 text-sm font-semibold", selectedSymbolRuntime?.quality?.clean ? "text-emerald-100" : "text-orange-100")}>
                {selectedSymbolRuntime?.quality?.clean ? "clean" : "check"}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-3 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {multiSymbolResults.map((row) => {
              const rowSymbol = String(row.symbol ?? "").toUpperCase();
              const clean = Boolean(row.quality?.clean);
              const active = rowSymbol === selectedSymbol;
              return (
                <button
                  key={`workspace-rail-${rowSymbol}`}
                  type="button"
                  onClick={() => setSymbol(rowSymbol)}
                  className={clsx(
                    "holo-button min-w-[116px] rounded-2xl border px-3 py-2 text-left transition",
                    active
                      ? "border-cyan-300/42 bg-cyan-400/16 text-white shadow-[0_0_24px_rgba(34,211,238,0.12)]"
                      : clean
                        ? "border-emerald-300/16 bg-emerald-400/8 text-white/72 hover:border-cyan-300/24"
                        : "border-orange-300/18 bg-orange-400/10 text-orange-100",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold">{rowSymbol}</span>
                    <span className={clsx("h-2 w-2 rounded-full", clean ? "bg-emerald-300" : "bg-orange-300")} />
                  </div>
                  <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-white/42">
                    {String(row.complete_1h_bars ?? 0)} 1H
                  </div>
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap gap-2 xl:justify-end">
            {timeframeOptions.map((item) => (
              <button
                key={`workspace-tf-${item}`}
                type="button"
                onClick={() => setTimeframe(item)}
                className={clsx(
                  "holo-button rounded-full border px-4 py-2 text-xs uppercase tracking-[0.22em] transition",
                  selectedTimeframe === item
                    ? "border-cyan-300/36 bg-cyan-400/16 text-cyan-50 shadow-[0_0_20px_rgba(34,211,238,0.12)]"
                    : "border-white/10 bg-white/5 text-white/62 hover:border-cyan-300/18 hover:text-white",
                )}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
      </section>

      <CandlePanel
        apiUrl={API_URL}
        endpointPath="/api/structural-lab/candles"
        panelLabel={`${selectedSymbolUsesActiveRuntime ? "Active Multi-Symbol Runtime" : "Shadow Forward"} Candle Wall / ${selectedSymbol} / ${selectedTimeframe}`}
        symbol={selectedSymbol}
        timeframe={selectedTimeframe}
        mode="structural_lab"
      />
      </>
      ) : null}
    </div>
  );

  const commandCenterContent = (
    <div className="grid gap-5">
      <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="relative overflow-hidden rounded-[34px] border border-emerald-300/24 bg-[radial-gradient(circle_at_16%_16%,rgba(16,185,129,0.22),transparent_30%),linear-gradient(135deg,rgba(4,18,28,0.97),rgba(3,8,18,0.94))] p-6 shadow-[0_18px_60px_rgba(5,150,105,0.12)]">
          <div className="flex flex-wrap items-start justify-between gap-6">
            <div>
              <div className="text-[11px] uppercase tracking-[0.34em] text-emerald-100/78">Active runtime truth</div>
              <h2 className="mt-3 text-4xl font-semibold text-white">
                {activeExecutedTrades > 0 ? "Trade activity recorded" : "No trade executed"}
              </h2>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-white/66">
                The scheduler is collecting candles and processing decision slots. Active runtime PnL remains zero
                until a real runtime trigger/execution event is recorded. Research/backtest values are separated from
                this operator truth.
              </p>
            </div>
            <div className="min-w-[220px] rounded-[28px] border border-white/12 bg-white/6 px-5 py-4 text-right">
              <div className="text-[10px] uppercase tracking-[0.28em] text-white/50">Active runtime PnL</div>
              <div className="mt-2 text-4xl font-semibold text-white">{formatMoney(activeRuntimePnlEur)}</div>
              <div className="mt-1 text-sm text-white/54">
                {activeExecutedTrades > 0 ? "runtime trade event recorded" : "no executed runtime trade"}
              </div>
            </div>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-4">
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Open positions</div>
              <div className="mt-2 text-2xl font-semibold text-white">{activeOpenPositions}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Trade triggers</div>
              <div className="mt-2 text-2xl font-semibold text-white">{String(activeExecutedTrades)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Trigger emails</div>
              <div className="mt-2 text-2xl font-semibold text-white">{String(tradeEmailsLastRun)}</div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Real-money path</div>
              <div className="mt-2 text-2xl font-semibold text-white">OFF</div>
            </div>
          </div>
        </section>

        <section className="rounded-[34px] border border-cyan-300/20 bg-[linear-gradient(145deg,rgba(6,24,42,0.9),rgba(5,10,21,0.94))] p-6">
          <div className="text-[11px] uppercase tracking-[0.34em] text-cyan-100/78">Live operator clocks</div>
          <div className="mt-3 text-3xl font-semibold text-white">
            {clientNowMs === null ? "syncing clock…" : formatTime(new Date(clientNowMs).toISOString())}
          </div>
          <div className="mt-4 grid gap-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Current 1m closes in</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatDuration(candleCloseCountdown)}</div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                <div className="h-full rounded-full bg-cyan-300 transition-[width] duration-1000" style={{ width: `${candleProgressPct}%` }} />
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
              <div className="text-[10px] uppercase tracking-[0.22em] text-white/45">Next scheduler run</div>
              <div className="mt-2 text-2xl font-semibold text-white">{formatDuration(multiSchedulerCountdown)}</div>
              <div className="mt-1 text-sm text-white/58">LaunchAgent loaded / every {String(multiSchedulerIntervalSeconds)}s</div>
            </div>
          </div>
        </section>
      </div>

      <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="cinematic-card rounded-[30px] border border-cyan-300/18 bg-[linear-gradient(135deg,rgba(5,25,43,0.92),rgba(6,10,22,0.9))] p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="text-[11px] uppercase tracking-[0.32em] text-cyan-100/74">Live operator pulse</div>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                {String(multiSymbolOperatorTape.status ?? "ACTIVE_NO_TRADE").replaceAll("_", " ")}
              </h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-white/62">
                {String(multiSymbolOperatorTape.runtime_truth ?? "No active runtime PnL is shown until a runtime trade event exists.")}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-right">
              <div className="text-[10px] uppercase tracking-[0.24em] text-white/45">recent 24h decision slots</div>
              <div className="mt-2 text-3xl font-semibold text-white">{String(multiSymbolOperatorTape.recent_24h_decision_slots ?? 0)}</div>
            </div>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-4">
            <MetricCard
              label="Observed span"
              value={`${number(multiSymbolOperatorTape.observed_decision_span_hours ?? 0, 1)}h`}
              subtext="from first to latest runtime decision slot"
              tone="cyan"
            />
            <MetricCard
              label="Median wait"
              value={`${number(multiSymbolOperatorTape.holdout_median_wait_after_exit_hours ?? 10, 1)}h`}
              subtext="holdout-style median wait after exit"
              tone="green"
            />
            <MetricCard
              label="Average wait"
              value={`${number(multiSymbolOperatorTape.holdout_average_wait_after_exit_hours ?? 16.34, 1)}h`}
              subtext="holdout-style average wait after exit"
              tone="green"
            />
            <MetricCard
              label="No-trade days"
              value={`${number(multiSymbolOperatorTape.holdout_zero_trade_day_pct ?? 27.62, 1)}%`}
              subtext="normal in the holdout diagnostic"
              tone="orange"
            />
          </div>
        </div>

        <div className="cinematic-card rounded-[30px] border border-emerald-300/18 bg-[linear-gradient(135deg,rgba(7,38,30,0.86),rgba(6,10,20,0.92))] p-5">
          <div className="text-[11px] uppercase tracking-[0.32em] text-emerald-100/74">After-tax mission reference</div>
          <h2 className="mt-2 text-2xl font-semibold text-white">Fees + tax reserve interpretation</h2>
          <p className="mt-2 text-sm leading-6 text-white/62">
            Research PnL is separated from active runtime PnL. This is the diagnostic mission reference, not live profit.
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <MetricCard
              label="Research after-tax equity"
              value={formatMoney(researchAfterTax.ending_total_equity_after_tax)}
              subtext={`net gain ${formatMoney(researchAfterTax.net_gain_after_tax)}`}
              tone="green"
            />
            <MetricCard
              label="Research tax reserve"
              value={formatMoney(researchAfterTax.tax_reserved_or_withdrawn)}
              subtext={`${String(researchAfterTax.selected_trades ?? 0)} selected trades`}
              tone="orange"
            />
            <MetricCard
              label="6M after-tax equity"
              value={formatMoney(holdoutAfterTax.ending_total_equity_after_tax)}
              subtext={`net gain ${formatMoney(holdoutAfterTax.net_gain_after_tax)}`}
              tone="cyan"
            />
            <MetricCard
              label="6M tax reserve"
              value={formatMoney(holdoutAfterTax.tax_reserved_or_withdrawn)}
              subtext={`${String(holdoutAfterTax.selected_trades ?? 0)} selected trades`}
              tone="orange"
            />
          </div>
        </div>
      </section>

      <section className="rounded-[34px] border border-white/10 bg-[linear-gradient(180deg,rgba(8,15,30,0.9),rgba(5,9,19,0.88))] p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.34em] text-cyan-100/72">Open a workspace</div>
            <h2 className="mt-2 text-2xl font-semibold text-white">Everything is behind tabs now</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-white/60">
              The command page stays short. Use these panels for candles, symbol health, structure, research numbers,
              trade review, and safety settings instead of scrolling through one long page.
            </p>
          </div>
          <div className="rounded-2xl border border-amber-300/18 bg-amber-400/10 px-4 py-3 text-sm text-amber-50">
            Research values such as {formatMoney(shadowNetCost.current_net_cost_diagnostic_equity)} are not active PnL.
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          {VIEWS.filter((item) => item.key !== "overview").map((item) => (
            <Link
              key={`workspace-${item.key}`}
              href={item.href}
              className="group rounded-[24px] border border-white/10 bg-white/5 px-4 py-4 transition hover:-translate-y-0.5 hover:border-cyan-300/30 hover:bg-cyan-400/10"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-white">
                  {item.icon}
                  <span className="font-semibold">{item.label}</span>
                </div>
                <ArrowRight className="h-4 w-4 text-white/38 transition group-hover:translate-x-1 group-hover:text-cyan-100" />
              </div>
              <div className="mt-3 text-xs uppercase tracking-[0.22em] text-white/42">{item.eyebrow}</div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );

  const content = {
    overview: commandCenterContent,
    "market-replay": candlesWorkspaceContent,
    "structure-map": structureMapContent,
    "profit-vault": profitVaultContent,
    "trade-review": tradeReviewContent,
    settings: settingsContent,
  }[view];

  return (
    <main className="min-h-screen bg-transparent px-5 py-6 text-white md:px-8 xl:px-10">
      <div className="mx-auto flex max-w-[1900px] flex-col gap-6">
        {view === "overview" ? (
        <header
          className={clsx(
            "relative overflow-hidden rounded-[38px] border border-white/10 bg-[linear-gradient(180deg,rgba(8,17,34,0.92),rgba(6,11,24,0.88))] shadow-[0_30px_120px_rgba(4,8,22,0.45)]",
            compactHero ? "p-4" : "p-6",
          )}
        >
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_12%_18%,rgba(83,242,255,0.18),transparent_22%),radial-gradient(circle_at_76%_14%,rgba(255,153,56,0.12),transparent_18%),radial-gradient(circle_at_72%_84%,rgba(52,211,153,0.12),transparent_22%)]" />
          <div className={clsx("relative grid xl:items-center", compactHero ? "gap-4 xl:grid-cols-[112px_minmax(0,1fr)]" : "gap-6 xl:grid-cols-[280px_minmax(0,1fr)]")}>
            <div className={clsx("relative hidden overflow-hidden rounded-[30px] border border-cyan-300/16 bg-[#050c1d] xl:block", compactHero ? "h-[96px]" : "h-[180px]")}>
              <Image
                src="/logo-hero.png"
                alt="Structural Compounding Lab"
                fill
                sizes="112px"
                className={clsx("object-contain drop-shadow-[0_0_28px_rgba(83,242,255,0.16)]", compactHero ? "scale-[1.01]" : "scale-[1.03]")}
                priority
              />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-cyan-300/28 bg-cyan-400/14 px-3 py-1 text-[10px] uppercase tracking-[0.34em] text-cyan-100">
                  Structural Compounding Lab
                </span>
                <span className="rounded-full border border-emerald-300/24 bg-emerald-400/12 px-3 py-1 text-[10px] uppercase tracking-[0.28em] text-emerald-100">
                  Shadow-forward operator cockpit
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[10px] uppercase tracking-[0.28em] text-white/65">
                  Read-only / isolated from paper-live runtime
                </span>
              </div>
              <h1 className={clsx("font-semibold tracking-[0.01em]", compactHero ? "mt-2 text-3xl md:text-[2.35rem]" : "mt-4 text-4xl md:text-[3rem]")}>Structural Command Lab</h1>
              <p className={clsx("max-w-4xl text-sm leading-7 text-white/70", compactHero ? "mt-2" : "mt-3")}>
                {compactHero
                  ? "Active multi-symbol shadow-forward cockpit: closed 1m candles, scheduler health, trade-trigger truth, safety gates, and separated research-only baselines."
                  : "Active multi-symbol shadow-forward cockpit: closed 1m candles, scheduler health, trade-trigger truth, safety gates, and separated research-only baselines."}
              </p>
              <div className={clsx("flex flex-wrap gap-3", compactHero ? "mt-3" : "mt-5")}>
                <Link
                  href="/"
                  className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/72 transition hover:border-cyan-300/20 hover:text-white"
                >
                  <ArrowRight className="h-4 w-4 rotate-180" />
                  Return to command center
                </Link>
                <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-white/68">
                  <Database className="h-4 w-4 text-cyan-200" />
                  {data?.lab?.has_run ? "reading external structural output" : "awaiting structural artifacts"}
                </div>
              </div>
            </div>
          </div>
        </header>
        ) : null}

        <nav className="sticky top-3 z-40 flex flex-wrap gap-3 rounded-[26px] border border-cyan-300/18 bg-slate-950/88 p-3 shadow-[0_18px_60px_rgba(0,0,0,0.28)] backdrop-blur-xl">
          {VIEWS.map((item) => {
            const active = item.key === activeView.key;
            return (
              <Link
                key={item.key}
                href={item.href}
                className={clsx(
                  "inline-flex flex-1 items-center justify-center gap-2 rounded-2xl border px-4 py-3 text-sm font-medium transition md:flex-none",
                  active
                    ? "border-cyan-300/35 bg-cyan-400/16 text-cyan-50 shadow-[0_0_20px_rgba(83,242,255,0.12)]"
                    : "border-white/10 bg-white/5 text-white/68 hover:border-cyan-300/18 hover:text-white",
                )}
              >
                {item.icon}
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {false && view !== "overview" ? (
          <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
              <MetricCard
                label="Multi-symbol runtime"
                value={String(multiSymbolRuntime.status_color ?? "n/a")}
                subtext={`${String(multiSymbolRuntime.symbols_clean ?? 0)} / ${String(multiSymbolRuntime.symbols_checked ?? 0)} symbols clean`}
                tone={multiRuntimeIsGreen ? "green" : "orange"}
              />
              <MetricCard
                label="Latest active 1m"
                value={formatTime(multiSymbolRuntime.latest_safe_1m_timestamp)}
                subtext={`${String(multiSymbolRuntime.total_appended_rows ?? 0)} rows appended last run`}
                tone="green"
              />
              <MetricCard
                label="Active PnL"
                value={formatMoney(activeRuntimePnlEur)}
                subtext={activeExecutedTrades > 0 ? "runtime trade event recorded" : "no executed runtime trade"}
                tone={activeExecutedTrades > 0 ? "green" : "cyan"}
              />
              <MetricCard
                label="Open positions"
                value={String(activeOpenPositions)}
                subtext="no broker/live position path enabled"
                tone="green"
              />
              <MetricCard
                label="Decision slots"
                value={String(multiSymbolDecisions.total_decision_slots ?? 0)}
                subtext={`new ${String(multiSymbolRuntime.total_new_decision_rows ?? 0)} / dupes ${String(multiSymbolRuntime.decision_ledger_duplicate_keys ?? 0)}`}
              />
              <MetricCard
                label="Safety"
                value={shadowSafety.paper_validation_ready ? "BLOCK" : "READ-ONLY"}
                subtext="paper/live/order/broker disabled"
                tone={shadowSafety.paper_validation_ready ? "orange" : "green"}
              />
              <MetricCard
                label="Evidence"
                value={String(multiSymbolRuntime.status_color ?? "n/a")}
                subtext={`${String(multiSymbolEvidence.minimum_complete_1h_slots ?? 0)} / ${String(multiSymbolEvidence.target_complete_1h_slots ?? 4320)} 1H evidence slots`}
                tone={multiRuntimeIsGreen ? "green" : "orange"}
              />
              <MetricCard
                label="Execution"
                value={paperReady || liveReady ? "ARMED" : "BLOCKED"}
                subtext="paper/live scaffold guarded"
                tone={paperReady || liveReady ? "orange" : "green"}
              />
            </div>

            <section className="overflow-hidden rounded-[30px] border border-cyan-300/18 bg-[linear-gradient(180deg,rgba(5,18,34,0.92),rgba(4,9,20,0.9))] px-5 py-4 shadow-[0_18px_70px_rgba(20,184,166,0.12)]">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <div className="flex flex-wrap items-center gap-3">
                    <span className={clsx("relative flex h-3 w-3", multiRuntimeIsGreen ? "text-emerald-300" : "text-orange-300")}>
                      <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-70" />
                      <span className="relative inline-flex h-3 w-3 rounded-full bg-current" />
                    </span>
                    <div className="text-[11px] uppercase tracking-[0.34em] text-cyan-100/80">Multi-symbol live operator tape</div>
                  </div>
                  <div className="mt-2 text-2xl font-semibold text-white">
                    {clientNowMs === null ? "syncing clock…" : formatTime(new Date(clientNowMs ?? Date.now()).toISOString())}
                  </div>
                  <div className="mt-2 max-w-4xl text-sm leading-6 text-white/62">
                    Visual clock updates every second. Data snapshot refreshes every 30 seconds. The chart API refreshes every 5 seconds and may append public unsigned Binance klines for display only. Active multi-symbol scheduler catches up every {String(multiSchedulerIntervalSeconds)} seconds.
                  </div>
                </div>
                <div className="grid min-w-[min(100%,900px)] flex-1 gap-3 md:grid-cols-4">
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.24em] text-white/45">Current 1m candle closes in</div>
                    <div className="mt-2 text-xl font-semibold text-white">{formatDuration(candleCloseCountdown)}</div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-white/10">
                      <div className="h-full rounded-full bg-cyan-300 transition-[width] duration-1000" style={{ width: `${candleProgressPct}%` }} />
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.24em] text-white/45">Next scheduler run</div>
                    <div className="mt-2 text-xl font-semibold text-white">{formatDuration(multiSchedulerCountdown)}</div>
                    <div
                      className="mt-2 truncate text-sm text-white/58"
                      title={String(multiSymbolScheduler.label ?? "multi-symbol LaunchAgent")}
                    >
                      LaunchAgent loaded / every {String(multiSchedulerIntervalSeconds)}s
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.24em] text-white/45">Active runtime latest</div>
                    <div className="mt-2 text-lg font-semibold text-white">{formatTime(multiSymbolRuntime.latest_safe_1m_timestamp)}</div>
                    <div className="mt-2 text-sm text-white/58">{String(multiSymbolRuntime.symbols_clean ?? 0)} / {String(multiSymbolRuntime.symbols_checked ?? 0)} symbols clean</div>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                    <div className="text-[10px] uppercase tracking-[0.24em] text-white/45">Trade triggers last run</div>
                    <div className="mt-2 text-lg font-semibold text-white">{String(multiSymbolRuntime.multi_asset_trade_trigger_rows_seen_this_run ?? 0)}</div>
                    <div className="mt-2 text-sm text-white/58">{String(multiSymbolRuntime.multi_asset_trade_trigger_emails_sent_this_run ?? 0)} emails / no live orders</div>
                  </div>
                </div>
              </div>
            </section>
          </>
        ) : null}

        {warningList.length ? (
          <Section eyebrow="Research warnings" title="Current Empty-State / Artifact Truth">
            <div className="grid gap-3">
              {warningList.map((warning) => (
                <div key={warning} className="rounded-2xl border border-orange-400/20 bg-orange-400/10 px-4 py-3 text-sm text-orange-100">
                  <div className="flex items-center gap-2">
                    <ShieldAlert className="h-4 w-4" />
                    <span>{warning}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        ) : null}

        {error ? (
          <Section eyebrow="Telemetry error" title="Structural Lab Snapshot">
            <TableEmpty message="Snapshot request failed. The lab remains read-only; refresh after the structural API comes up." />
          </Section>
        ) : null}
        {!error && !data ? (
          <Section eyebrow="Loading live telemetry" title="Waiting For Structural Lab Snapshot">
            <div className="rounded-[24px] border border-cyan-300/16 bg-cyan-400/10 px-4 py-4 text-sm leading-7 text-cyan-50/82">
              The dashboard is waiting for the active snapshot API. It will not render zero/default KPI values as if
              they were real runtime state.
            </div>
          </Section>
        ) : null}
        {!error && data ? content : null}
      </div>
    </main>
  );
}
