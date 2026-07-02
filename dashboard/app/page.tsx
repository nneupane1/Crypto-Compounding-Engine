import Image from "next/image";
import Link from "next/link";
import {
  Activity,
  ArrowRight,
  BarChart3,
  CandlestickChart,
  Radar,
  Shield,
  Waves,
} from "lucide-react";

const MODES = [
  {
    href: "/paper",
    title: "Paper Execution",
    eyebrow: "live paper trading rail",
    accent: "from-sky-400/25 via-cyan-400/12 to-transparent",
    border: "border-sky-300/18 hover:border-sky-200/40",
    copy:
      "Real-time paper engine telemetry, market ingestion, signal evaluation, allocator routing, and execution-state observability.",
  },
  {
    href: "/backtest",
    title: "Backtest Lab",
    eyebrow: "historical replay rail",
    accent: "from-amber-400/25 via-orange-400/12 to-transparent",
    border: "border-amber-300/18 hover:border-amber-200/40",
    copy:
      "Validation artefacts, replay-driven chart inspection, routed sleeve diagnostics, and historical allocator behaviour under pressure.",
  },
  {
    href: "/live",
    title: "Live Operations",
    eyebrow: "runtime command rail",
    accent: "from-emerald-400/25 via-teal-400/12 to-transparent",
    border: "border-emerald-300/18 hover:border-emerald-200/40",
    copy:
      "Operational command deck for runtime health, synchronization, guard state, and future live-execution readiness on the same spatial layout.",
  },
  {
    href: "/structural-lab",
    title: "Structural Lab",
    eyebrow: "separate research rail",
    accent: "from-fuchsia-400/25 via-cyan-400/10 to-transparent",
    border: "border-fuchsia-300/18 hover:border-fuchsia-200/40",
    copy:
      "Isolated support/resistance, liquidity, EMA, pyramiding, cooldown, and profit-vault research cockpit scaffold, kept outside the active paper/backtest/live stack.",
  },
];

const MODULES = [
  { label: "Market Theatre", icon: <CandlestickChart className="h-4 w-4" /> },
  { label: "Portfolio Intelligence", icon: <BarChart3 className="h-4 w-4" /> },
  { label: "Allocator Forensics", icon: <Radar className="h-4 w-4" /> },
  { label: "Runtime Shield", icon: <Shield className="h-4 w-4" /> },
  { label: "Signal Flow", icon: <Waves className="h-4 w-4" /> },
  { label: "Engine Pulse", icon: <Activity className="h-4 w-4" /> },
];

export default function HomePage() {
  return (
    <main className="min-h-screen overflow-hidden px-5 py-8 text-white md:px-8 xl:px-10">
      <div className="mx-auto flex max-w-[1900px] flex-col gap-8">
        <section className="cinematic-card glass-panel relative overflow-hidden rounded-[42px] border border-white/10 px-6 py-8 shadow-[0_30px_120px_rgba(4,8,22,0.45)] md:px-8 md:py-10">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(83,242,255,0.22),transparent_25%),radial-gradient(circle_at_80%_18%,rgba(255,153,56,0.18),transparent_20%),radial-gradient(circle_at_60%_90%,rgba(52,211,153,0.14),transparent_22%)]" />
          <div className="absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] [background-size:28px_28px]" />
          <div className="relative grid gap-8 xl:grid-cols-[360px_minmax(0,1fr)] xl:items-center">
            <div className="relative h-[260px] overflow-hidden rounded-[34px] border border-cyan-300/18 bg-[linear-gradient(145deg,rgba(9,19,39,0.88),rgba(7,14,29,0.66)_42%,rgba(12,26,52,0.84))] shadow-[0_26px_80px_rgba(0,0,0,0.34)]">
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(83,242,255,0.18),transparent_42%)]" />
              <Image
                src="/logo-hero.png"
                alt="Retail Trading System hero logo"
                fill
                priority
                className="object-contain scale-[1.08] drop-shadow-[0_0_36px_rgba(83,242,255,0.16)]"
              />
            </div>

            <div className="relative">
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-cyan-300/28 bg-cyan-400/14 px-3 py-1 text-[10px] uppercase tracking-[0.34em] text-cyan-100">
                  Retail Trading System
                </span>
                <span className="rounded-full border border-emerald-300/24 bg-emerald-400/12 px-3 py-1 text-[10px] uppercase tracking-[0.28em] text-emerald-100">
                  Multi-Mode Cockpit
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[10px] uppercase tracking-[0.28em] text-white/65">
                  Backtest / Paper / Runtime
                </span>
              </div>

              <h1 className="mt-5 max-w-4xl text-4xl font-semibold tracking-[0.01em] md:text-[3.4rem]">
                Command Center
              </h1>
              <p className="mt-4 max-w-4xl text-base leading-8 text-slate-200/78">
                One institutional command layer for research replay, paper execution, and runtime operations.
                The layout stays spatially stable while the mode changes, so backtest evidence, live-paper
                behaviour, and operational state stay visually connected instead of scattered across separate tools.
              </p>

              <div className="mt-6 flex flex-wrap gap-3">
                {MODULES.map((module) => (
                  <div
                    key={module.label}
                    className="holo-button inline-flex items-center gap-2 rounded-2xl border border-white/10 bg-white/6 px-4 py-2 text-sm text-white/72 backdrop-blur-xl"
                  >
                    <span className="text-cyan-200">{module.icon}</span>
                    <span>{module.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-2 2xl:grid-cols-4">
          {MODES.map((mode) => (
            <Link
              key={mode.href}
              href={mode.href}
              className={`cinematic-card holo-button group relative overflow-hidden rounded-[34px] border bg-[linear-gradient(180deg,rgba(10,16,30,0.88),rgba(7,11,23,0.78))] p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_28px_70px_rgba(5,10,28,0.34)] ${mode.border}`}
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${mode.accent}`} />
              <div className="absolute inset-0 opacity-0 transition-opacity duration-300 group-hover:opacity-100 bg-[radial-gradient(circle_at_top,rgba(255,255,255,0.08),transparent_42%)]" />
              <div className="relative">
                <div className="text-[10px] uppercase tracking-[0.32em] text-white/48">{mode.eyebrow}</div>
                <div className="mt-4 flex items-center justify-between gap-4">
                  <h2 className="text-2xl font-semibold text-white">{mode.title}</h2>
                  <span className="rounded-full border border-white/14 bg-white/6 p-2 text-cyan-100 transition-transform duration-300 group-hover:translate-x-1">
                    <ArrowRight className="h-4 w-4" />
                  </span>
                </div>
                <p className="mt-4 text-sm leading-7 text-white/66">{mode.copy}</p>
                <div className="mt-6 inline-flex items-center gap-2 rounded-full border border-white/12 bg-white/6 px-3 py-1 text-[11px] uppercase tracking-[0.22em] text-white/68">
                  Enter cockpit
                  <ArrowRight className="h-3.5 w-3.5" />
                </div>
              </div>
            </Link>
          ))}
        </section>
      </div>
    </main>
  );
}
