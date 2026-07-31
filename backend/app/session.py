from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import json
import threading
import time
import uuid

from app.config import settings


class SessionWriter:
    def __init__(self, max_events: int | None = None) -> None:
        settings.session_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.id = f"{stamp}-{uuid.uuid4().hex[:8]}"
        self.path = settings.session_dir / f"{self.id}.jsonl"
        self.max_events = max_events if max_events is not None else settings.trace_max_events
        self.started_monotonic = time.monotonic()
        self.event_count = 0
        self.dropped_events = 0
        self.event_types: Counter[str] = Counter()
        self._limit_reported = False
        self._lock = threading.Lock()

    def write(self, event: dict) -> None:
        with self._lock:
            if self.max_events > 0 and self.event_count >= self.max_events:
                self.dropped_events += 1
                if not self._limit_reported:
                    self._limit_reported = True
                    self._append({
                        "type": "trace_limit_reached",
                        "max_events": self.max_events,
                    }, count=False)
                return
            self._append(event)

    def _append(self, event: dict, *, count: bool = True) -> None:
        event_type = str(event.get("type", "unknown"))
        payload = {
            "session_id": self.id,
            "event_index": self.event_count,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_ms": round((time.monotonic() - self.started_monotonic) * 1000, 3),
            **event,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if count:
            self.event_count += 1
            self.event_types[event_type] += 1

    def summary(self) -> dict:
        return {
            "session_id": self.id,
            "trace_file": str(self.path.resolve()),
            "duration_ms": round((time.monotonic() - self.started_monotonic) * 1000, 3),
            "event_count": self.event_count,
            "dropped_events": self.dropped_events,
            "event_types": dict(sorted(self.event_types.items())),
        }

    def finish(self) -> dict:
        summary = self.summary()
        self.write({"type": "session_summary", **summary})
        return self.summary()
