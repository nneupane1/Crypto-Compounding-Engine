"use client";

import { useMemo, useState } from "react";
import clsx from "clsx";

export type TradeFrequencyPnlPeriodRow = {
  period: string;
  trade_count: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  gross_pnl: number;
  net_pnl?: number | null;
  avg_pnl_per_trade: number;
  median_pnl_per_trade: number;
  total_R?: number | null;
  avg_R?: number | null;
  best_trade_pnl?: number | null;
  worst_trade_pnl?: number | null;
  top_symbol: string;
  top_strategy_or_sleeve: string;
  top_trade_reason: string;
  long_count: number;
  short_count: number;
};

export type TradeFrequencyPnlPayload = {
  summary: {
    current_day_trade_count: number;
    current_week_trade_count: number;
    current_month_trade_count: number;
    current_year_trade_count: number;
    avg_pnl_per_trade: number;
    avg_r_per_trade?: number | null;
    win_rate: number;
    best_trade_pnl?: number | null;
    worst_trade_pnl?: number | null;
  };
  daily: TradeFrequencyPnlPeriodRow[];
  weekly: TradeFrequencyPnlPeriodRow[];
  monthly: TradeFrequencyPnlPeriodRow[];
  yearly: TradeFrequencyPnlPeriodRow[];
  metadata: {
    source_files: string[];
    last_updated: string;
    row_count: number;
    missing_fields: string[];
    excluded_open_or_unrealized_rows?: number;
    pnl_basis?: string;
    read_only: boolean;
  };
};

function formatMoney(value: unknown) {
  if (value == null || Number.isNaN(Number(value))) {
    return "N/A";
  }
  const numeric = Number(value);
  const sign = numeric < 0 ? "-" : "";
  const absolute = Math.abs(numeric);
  const [integer, decimal] = absolute.toFixed(2).split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}€${grouped}.${decimal}`;
}

function formatPct(value: unknown, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function formatNumber(value: unknown, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) {
    return "N/A";
  }
  return Number(value).toFixed(digits);
}

const PERIODS = [
  { key: "daily", label: "Daily" },
  { key: "weekly", label: "Weekly" },
  { key: "monthly", label: "Monthly" },
  { key: "yearly", label: "Yearly" },
] as const;

export function TradeFrequencyPnlPanel({
  payload,
  title = "Trade Frequency & PnL",
  subtitle = "Read-only realized trade aggregation",
}: {
  payload?: TradeFrequencyPnlPayload;
  title?: string;
  subtitle?: string;
}) {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]["key"]>("daily");
  const rows = useMemo(() => {
    if (!payload) {
      return [];
    }
    return payload[period] ?? [];
  }, [payload, period]);

  const summary = payload?.summary;
  const metadata = payload?.metadata;
  const hasData = Boolean(payload && metadata && metadata.row_count > 0);

  return (
    <div className="grid gap-4">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-[0.28em] text-cyan-200/72">{subtitle}</div>
          <h3 className="mt-2 text-xl font-semibold text-white">{title}</h3>
        </div>
        <div className="text-xs text-white/50">
          {metadata?.read_only ? "read-only telemetry" : "read-only"} | {metadata?.pnl_basis ?? "realized_only"} | rows {metadata?.row_count ?? 0}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
        <PanelKpi label="Trades today" value={String(summary?.current_day_trade_count ?? 0)} />
        <PanelKpi label="Trades this week" value={String(summary?.current_week_trade_count ?? 0)} />
        <PanelKpi label="Trades this month" value={String(summary?.current_month_trade_count ?? 0)} />
        <PanelKpi label="Trades this year" value={String(summary?.current_year_trade_count ?? 0)} />
        <PanelKpi label="Avg PnL / trade" value={formatMoney(summary?.avg_pnl_per_trade)} tone={Number(summary?.avg_pnl_per_trade ?? 0) >= 0 ? "good" : "warning"} />
        <PanelKpi label="Avg R / trade" value={formatNumber(summary?.avg_r_per_trade)} />
        <PanelKpi label="Win rate" value={formatPct(summary?.win_rate)} tone={Number(summary?.win_rate ?? 0) >= 0.5 ? "good" : "warning"} />
        <PanelKpi label="Best trade" value={formatMoney(summary?.best_trade_pnl)} tone="good" />
        <PanelKpi label="Worst trade" value={formatMoney(summary?.worst_trade_pnl)} tone="warning" />
      </div>

      <div className="flex flex-wrap gap-2">
        {PERIODS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => setPeriod(item.key)}
            className={clsx(
              "holo-button rounded-full border px-3 py-1.5 text-xs uppercase tracking-[0.18em] transition",
              period === item.key
                ? "border-cyan-300/28 bg-cyan-400/12 text-cyan-100"
                : "border-white/10 bg-white/5 text-white/58 hover:border-cyan-300/16 hover:text-white",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {hasData ? (
        <div className="cinematic-card overflow-x-auto rounded-[24px] border border-white/10 bg-white/5">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-white/8 text-white/45">
              <tr>
                <th className="px-4 py-3 font-medium">Period</th>
                <th className="px-4 py-3 font-medium">Trades</th>
                <th className="px-4 py-3 font-medium">Win rate</th>
                <th className="px-4 py-3 font-medium">Gross PnL</th>
                <th className="px-4 py-3 font-medium">Net PnL</th>
                <th className="px-4 py-3 font-medium">Avg PnL</th>
                <th className="px-4 py-3 font-medium">Avg R</th>
                <th className="px-4 py-3 font-medium">Best / Worst</th>
                <th className="px-4 py-3 font-medium">Top symbol</th>
                <th className="px-4 py-3 font-medium">Top sleeve</th>
                <th className="px-4 py-3 font-medium">Top reason</th>
                <th className="px-4 py-3 font-medium">Long / Short</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.period} className="border-t border-white/6">
                  <td className="px-4 py-3 font-medium text-white">{row.period}</td>
                  <td className="px-4 py-3 text-white/72">{row.trade_count} ({row.winning_trades}/{row.losing_trades})</td>
                  <td className="px-4 py-3 text-white/72">{formatPct(row.win_rate)}</td>
                  <td className={clsx("px-4 py-3 font-medium", Number(row.gross_pnl) >= 0 ? "text-emerald-300" : "text-orange-300")}>{formatMoney(row.gross_pnl)}</td>
                  <td className="px-4 py-3 text-white/72">{formatMoney(row.net_pnl)}</td>
                  <td className="px-4 py-3 text-white/72">{formatMoney(row.avg_pnl_per_trade)}</td>
                  <td className="px-4 py-3 text-white/72">{formatNumber(row.avg_R)}</td>
                  <td className="px-4 py-3 text-white/72">
                    {formatMoney(row.best_trade_pnl)} / {formatMoney(row.worst_trade_pnl)}
                  </td>
                  <td className="px-4 py-3 text-white/72">{row.top_symbol}</td>
                  <td className="px-4 py-3 text-white/72">{row.top_strategy_or_sleeve}</td>
                  <td className="px-4 py-3 text-white/72">{row.top_trade_reason}</td>
                  <td className="px-4 py-3 text-white/72">{row.long_count} / {row.short_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="cinematic-card rounded-[24px] border border-white/10 bg-white/5 px-4 py-5 text-sm text-white/58">
          No realized trade-frequency dataset is available yet.
        </div>
      )}

      <div className="cinematic-card rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-xs text-white/55">
        source {metadata?.source_files?.[0] ?? "n/a"} | last updated {metadata?.last_updated ?? "n/a"} | excluded unrealized/open rows {metadata?.excluded_open_or_unrealized_rows ?? 0}
        {metadata?.missing_fields?.length ? ` | missing fields ${metadata.missing_fields.join(", ")}` : ""}
      </div>
    </div>
  );
}

function PanelKpi({
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
      ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-100"
      : tone === "warning"
        ? "border-orange-400/20 bg-orange-400/10 text-orange-100"
        : "border-white/10 bg-white/5 text-white";
  return (
    <div className={clsx("cinematic-card rounded-2xl border px-4 py-3", toneClass)}>
      <div className="text-[10px] uppercase tracking-[0.22em] text-white/52">{label}</div>
      <div className="mt-2 text-xl font-semibold">{value}</div>
    </div>
  );
}
