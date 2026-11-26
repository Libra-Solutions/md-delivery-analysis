from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, List, Mapping, Optional

import httpx

from delivery_analysis.app.refresh import RefreshWorker
from delivery_analysis.settings import Settings, redact, secret_values


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AppContext:
    db_path: Path
    settings: Settings
    environ: Mapping[str, str]
    worker: RefreshWorker
    transport: Optional[httpx.BaseTransport] = None
    clock: Callable[[], datetime] = field(default=_utc_now)
    started_at: str = field(default_factory=lambda: _utc_now().isoformat())
    write_count: int = 0

    def today(self) -> date:
        return self.clock().astimezone(self.settings.report_tz).date()

    def secrets(self) -> List[str]:
        return secret_values(self.environ)

    def clean(self, text: Optional[str]) -> Optional[str]:
        return None if text is None else redact(text, self.secrets())
