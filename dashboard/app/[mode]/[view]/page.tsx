import { notFound } from "next/navigation";
import { DashboardShell } from "@/components/dashboard-shell";

const VALID_MODES = new Set(["paper", "backtest", "live"]);
const VALID_VIEWS = new Set(["overview", "market", "atlas", "portfolio", "allocator", "runtime"]);

export default async function ModeViewPage({
  params,
}: {
  params: Promise<{ mode: string; view: string }>;
}) {
  const { mode, view } = await params;
  if (!VALID_MODES.has(mode) || !VALID_VIEWS.has(view)) {
    notFound();
  }
  return (
    <DashboardShell
      mode={mode as "paper" | "backtest" | "live"}
      view={view as "overview" | "market" | "atlas" | "portfolio" | "allocator" | "runtime"}
    />
  );
}
