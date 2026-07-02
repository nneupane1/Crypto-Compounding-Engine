import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Retail Trading System | Command Center",
  description: "Institutional multi-mode trading cockpit for backtest intelligence, paper execution, and runtime operations."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
