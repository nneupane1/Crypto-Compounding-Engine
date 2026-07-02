import { notFound } from "next/navigation";
import { DashboardShell } from "@/components/dashboard-shell";

const VALID_MODES = new Set(["paper", "backtest", "live"]);

export default async function ModePage({
  params,
}: {
  params: Promise<{ mode: string }>;
}) {
  const { mode } = await params;
  if (!VALID_MODES.has(mode)) {
    notFound();
  }
  return <DashboardShell mode={mode as "paper" | "backtest" | "live"} view="overview" />;
}
