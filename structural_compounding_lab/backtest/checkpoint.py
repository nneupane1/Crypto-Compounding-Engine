from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class StructuralCheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict[str, Any] | None:
        if not self.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        normalized = self._normalize(payload)
        temp_path = self.path.parent / f"{self.path.name}.tmp"
        for attempt in range(8):
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
                temp_path.replace(self.path)
                return
            except (PermissionError, FileNotFoundError):
                if attempt == 7:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def clear(self) -> None:
        if self.exists():
            self.path.unlink()

    def _normalize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._normalize(item) for item in value]
        if hasattr(value, "item") and callable(value.item):
            return value.item()
        if hasattr(value, "isoformat") and callable(value.isoformat):
            return value.isoformat()
        return value
