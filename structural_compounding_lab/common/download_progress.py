from __future__ import annotations

import builtins
from collections import deque
from datetime import datetime
from typing import Any

try:
    from rich import box
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - terminal enhancement only
    RICH_AVAILABLE = False


def _fmt_duration(seconds: float) -> str:
    seconds_i = max(0, int(seconds))
    hours, remainder = divmod(seconds_i, 3600)
    minutes, seconds_i = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds_i}s"
    if minutes:
        return f"{minutes}m {seconds_i}s"
    return f"{seconds_i}s"


class DownloadProgressDisplay:
    """Rich progress display owned by the compounding package."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and RICH_AVAILABLE
        self.console = Console() if self.enabled else None
        self.live: Any | None = None
        self.progress: Any | None = None
        self.task_id: Any | None = None
        self.events: deque[tuple[str, str, str]] = deque(maxlen=8)
        self.state: dict[str, Any] = {}

    def _disable_due_to_encoding(self, exc: Exception) -> None:
        try:
            if self.live is not None:
                self.live.stop()
        except Exception:
            pass
        self.live = None
        self.progress = None
        self.task_id = None
        self.enabled = False
        self.console = None
        builtins.print("Rich progress disabled due to console encoding limits; using plain output.")
        builtins.print(f"Reason: {exc}")

    def start(
        self,
        symbol: str,
        interval: str,
        start_date: str,
        end_date: str,
        final_path: str,
        checkpoint_path: str,
        resumed: bool = False,
        resume_point: str | None = None,
        total_rows: int = 0,
        initial_progress_pct: float = 0.0,
        verify_mode: str = "enabled",
    ) -> None:
        if not self.enabled:
            return

        self.state = {
            "symbol": symbol,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "final_path": str(final_path),
            "checkpoint_path": str(checkpoint_path),
            "phase": "Preparing download",
            "current_batch": "-",
            "current_window": "-",
            "batch_rows": "-",
            "total_rows": total_rows,
            "progress_pct": initial_progress_pct,
            "remaining_pct": max(0.0, 100.0 - initial_progress_pct),
            "elapsed": "0s",
            "eta": "-",
            "resume_point": resume_point or "-",
            "verify_mode": verify_mode,
        }

        self.progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None, complete_style="green", finished_style="green"),
            TaskProgressColumn(),
            TextColumn("|"),
            TimeElapsedColumn(),
            TextColumn("| ETA"),
            TimeRemainingColumn(),
            expand=True,
            console=self.console,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self.task_id = self.progress.add_task(
            f"Downloading {symbol} {interval} history",
            total=100,
            completed=initial_progress_pct,
        )

        try:
            self.live = Live(self._build_renderable(), console=self.console, refresh_per_second=6, transient=False)
            self.live.start()
        except UnicodeEncodeError as exc:
            self._disable_due_to_encoding(exc)
            return

        if resumed:
            self.add_event("resume", f"Resuming from {resume_point} with {total_rows} stored rows")
            self.state["phase"] = "Resuming download"
        else:
            self.add_event("start", "Starting from the beginning")
            self.state["phase"] = "Starting download"

        self.refresh()

    def stop(self) -> None:
        if self.enabled and self.live is not None:
            self.live.stop()
            self.live = None

    def add_event(self, level: str, message: str) -> None:
        if not self.enabled:
            return
        self.events.appendleft((datetime.now().strftime("%H:%M:%S"), level.upper(), message))
        self.refresh()

    def update_request(self, batch_number: int, request_from: str, limit: int) -> None:
        if not self.enabled:
            return
        self.state["phase"] = "Requesting batch"
        self.state["current_batch"] = batch_number
        self.state["current_window"] = f"from {request_from}"
        self.state["batch_rows"] = f"limit {limit}"
        self.refresh()

    def update_batch_result(
        self,
        batch_number: int,
        window_start: str,
        window_end: str,
        batch_rows: int,
        total_rows: int,
        progress_pct: float,
        remaining_pct: float,
        elapsed_seconds: float,
        eta_seconds: float,
        resume_point: str,
    ) -> None:
        if not self.enabled:
            return
        self.state["phase"] = "Batch saved"
        self.state["current_batch"] = batch_number
        self.state["current_window"] = f"{window_start} -> {window_end}"
        self.state["batch_rows"] = batch_rows
        self.state["total_rows"] = total_rows
        self.state["progress_pct"] = progress_pct
        self.state["remaining_pct"] = remaining_pct
        self.state["elapsed"] = _fmt_duration(elapsed_seconds)
        self.state["eta"] = _fmt_duration(eta_seconds)
        self.state["resume_point"] = resume_point
        self.progress.update(self.task_id, completed=progress_pct)
        self.add_event("saved", f"Batch {batch_number} saved | {batch_rows} rows | total {total_rows}")

    def update_finalizing(self) -> None:
        if self.enabled:
            self.state["phase"] = "Finalizing CSV"
            self.add_event("finalize", "Download loop complete, writing final CSV")

    def update_completed(self, total_rows: int, total_time_seconds: float, final_path: str) -> None:
        if not self.enabled:
            return
        self.state["phase"] = "Completed"
        self.state["total_rows"] = total_rows
        self.state["elapsed"] = _fmt_duration(total_time_seconds)
        self.state["eta"] = "0s"
        self.state["progress_pct"] = 100.0
        self.state["remaining_pct"] = 0.0
        self.progress.update(self.task_id, completed=100)
        self.add_event("done", f"Saved final CSV -> {final_path}")

    def update_interrupted(self, reason: Exception, checkpoint_path: str) -> None:
        if self.enabled:
            message = "Interrupted by user" if not str(reason) else str(reason)
            self.state["phase"] = "Interrupted"
            self.add_event("stop", f"{self._truncate(message, 90)} | checkpoint {checkpoint_path}")

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        return text if len(str(text)) <= max_length else f"{str(text)[:max_length - 3]}..."

    def _build_status_table(self) -> Any:
        table = Table(title="Download Status", box=box.SIMPLE_HEAVY, expand=True, show_header=False)
        table.add_column("Field", style="bold cyan", no_wrap=True)
        table.add_column("Value", style="white")
        table.add_row("Phase", str(self.state["phase"]))
        table.add_row("Batch", str(self.state["current_batch"]))
        table.add_row("Window", str(self.state["current_window"]))
        table.add_row("Batch rows", str(self.state["batch_rows"]))
        table.add_row("Total rows", f"{self.state['total_rows']:,}")
        table.add_row("Progress", f"{self.state['progress_pct']:.2f}% complete ({self.state['remaining_pct']:.2f}% remaining)")
        table.add_row("Elapsed", self.state["elapsed"])
        table.add_row("ETA", self.state["eta"])
        table.add_row("Resume point", str(self.state["resume_point"]))
        table.add_row("TLS verify", str(self.state["verify_mode"]))
        table.add_row("Final CSV", self.state["final_path"])
        table.add_row("Checkpoint", self.state["checkpoint_path"])
        return table

    def _build_events_table(self) -> Any:
        table = Table(title="Recent Events", box=box.SIMPLE, expand=True)
        table.add_column("Time", style="dim", no_wrap=True)
        table.add_column("Level", style="bold", no_wrap=True)
        table.add_column("Message", overflow="fold")
        if not self.events:
            table.add_row("-", "-", "No events yet")
            return table
        for timestamp, level, message in self.events:
            level_style = {
                "START": "green",
                "RESUME": "yellow",
                "SAVED": "green",
                "FINALIZE": "cyan",
                "DONE": "bold green",
                "STOP": "bold red",
            }.get(level, "white")
            table.add_row(timestamp, f"[{level_style}]{level}[/{level_style}]", message)
        return table

    def _build_renderable(self) -> Any:
        header = Panel(
            f"[bold]Historical Download[/bold]  [cyan]{self.state['symbol']}[/cyan]  [magenta]{self.state['interval']}[/magenta]",
            title="Structural Compounding Lab",
            subtitle=f"{self.state['start_date']} -> {self.state['end_date']}",
            expand=True,
        )
        return Group(header, Panel(self.progress, title="Progress", expand=True), self._build_status_table(), self._build_events_table())

    def refresh(self) -> None:
        if self.enabled and self.live is not None:
            try:
                self.live.update(self._build_renderable(), refresh=True)
            except UnicodeEncodeError as exc:
                self._disable_due_to_encoding(exc)
