"""JSON-backed calendar store for Kokoron.

Stores events in a single JSON file with date-based indexing.
Provides CRUD operations and date-range queries.
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


class CalendarStore:
    """File-based calendar event store.

    Events are persisted as a JSON file at ``storage_path``.
    Thread-safety is ensured via an asyncio lock on all read/write ops.
    """

    def __init__(self, storage_path: str = "./data/calendar/events.json"):
        self._path = Path(storage_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._seq = 0
        self._events: list[dict] = []
        self._load()
        logger.info(
            f"CalendarStore initialized: {len(self._events)} events, "
            f"path={self._path}"
        )

    # ── Persistence ──

    def _load(self):
        """Load events from disk."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._events = data.get("events", [])
            self._seq = data.get("seq", 0)
        except Exception as e:
            logger.warning(f"Failed to load calendar: {e}")

    def _save(self):
        """Persist events to disk (atomic write)."""
        data = {
            "seq": self._seq,
            "events": self._events,
        }
        tmp_path = self._path.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._path)
        except Exception as e:
            logger.error(f"Failed to save calendar: {e}")

    # ── ID generation ──

    def _next_id(self) -> str:
        self._seq += 1
        return f"evt_{datetime.now().strftime('%Y%m%d')}_{self._seq:03d}"

    # ── CRUD ──

    async def add_event(
        self,
        title: str,
        date: str,
        time: str | None = None,
        end_time: str | None = None,
        location: str | None = None,
        notes: str | None = None,
    ) -> str:
        """Add a calendar event. Returns the event_id."""
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid date format: {date} (expected YYYY-MM-DD)")

        if time:
            if not re.match(r"^\d{2}:\d{2}$", time):
                raise ValueError(f"Invalid time format: {time} (expected HH:MM)")

        async with self._lock:
            event_id = self._next_id()
            event: dict = {
                "id": event_id,
                "title": title,
                "date": date,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }
            if time:
                event["time"] = time
            if end_time:
                event["end_time"] = end_time
            if location:
                event["location"] = location
            if notes:
                event["notes"] = notes

            self._events.append(event)
            self._save()

        logger.info(f"Calendar event added: {event_id} [{date}] {title}")
        return event_id

    async def list_events(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """List events in a date range. Defaults to today onwards."""
        if from_date is None:
            from_date = datetime.now().strftime("%Y-%m-%d")

        async with self._lock:
            filtered = []
            for evt in self._events:
                if evt["date"] < from_date:
                    continue
                if to_date and evt["date"] > to_date:
                    continue
                filtered.append(evt)

            # Sort by date then time
            filtered.sort(key=lambda e: e["date"] + (e.get("time") or "00:00"))
            return filtered[:limit]

    async def get_event(self, event_id: str) -> dict | None:
        """Get a single event by ID."""
        async with self._lock:
            for evt in self._events:
                if evt["id"] == event_id:
                    return evt
            return None

    async def update_event(self, event_id: str, **fields) -> bool:
        """Update an event's fields. Returns True if found and updated."""
        async with self._lock:
            for evt in self._events:
                if evt["id"] == event_id:
                    for key, value in fields.items():
                        if key in ("title", "date", "time", "end_time",
                                   "location", "notes") and value is not None:
                            evt[key] = value
                    evt["updated_at"] = datetime.now().isoformat()
                    self._save()
                    logger.info(f"Calendar event updated: {event_id}")
                    return True
            return False

    async def delete_event(self, event_id: str) -> bool:
        """Delete an event by ID. Returns True if found and deleted."""
        async with self._lock:
            for i, evt in enumerate(self._events):
                if evt["id"] == event_id:
                    self._events.pop(i)
                    self._save()
                    logger.info(f"Calendar event deleted: {event_id}")
                    return True
            return False

    async def get_upcoming(self, days: int = 7, limit: int = 5) -> list[dict]:
        """Get upcoming events within N days from today."""
        today = datetime.now().strftime("%Y-%m-%d")
        end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        return await self.list_events(from_date=today, to_date=end, limit=limit)
