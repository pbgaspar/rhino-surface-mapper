"""Minimal incremental reader for current Elite Dangerous Journal identity."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_JOURNAL_NAME = re.compile(
    r"Journal\.(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{6})\.(?P<sequence>\d+)\.log$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class JournalIdentity:
    """Current system identity reported by the active Journal session."""

    system: str
    body: str | None = None


class JournalIdentityReader:
    """Read only the current system identity from the active Journal file."""

    def __init__(self, journal_directory: str | Path | None = None) -> None:
        self.journal_directory = Path(journal_directory) if journal_directory else (
            Path.home() / 'Saved Games' / 'Frontier Developments' / 'Elite Dangerous')
        self._active_path: Path | None = None
        self._offset = 0
        self._pending = b''
        self._identity: JournalIdentity | None = None

    def reset(self) -> None:
        """Discard live identity and file position for a new game session."""
        self._active_path = None
        self._offset = 0
        self._pending = b''
        self._identity = None

    def current_identity(self) -> JournalIdentity | None:
        """Consume new Journal records and return the latest known identity."""
        path = self._latest_journal()
        if path is None:
            return self._identity
        if path != self._active_path:
            self._active_path = path
            self._offset = 0
            self._pending = b''
            self._identity = None
        try:
            size = path.stat().st_size
            if size < self._offset:
                self._offset = 0
                self._pending = b''
                self._identity = None
            with path.open('rb') as journal:
                journal.seek(self._offset)
                chunk = journal.read()
        except OSError:
            return self._identity
        if not chunk:
            return self._identity

        data = self._pending + chunk
        lines = data.splitlines(keepends=True)
        complete = lines
        self._pending = b''
        if lines and not lines[-1].endswith((b'\n', b'\r')):
            complete = lines[:-1]
            self._pending = lines[-1]
        # The file position advances over both complete lines and the retained
        # incomplete fragment; the fragment is reattached to the next read.
        self._offset += len(chunk)
        for line in complete:
            self._consume_line(line)
        return self._identity

    def _latest_journal(self) -> Path | None:
        try:
            candidates = []
            for path in self.journal_directory.glob('Journal.*.log'):
                match = _JOURNAL_NAME.fullmatch(path.name)
                if match:
                    candidates.append((
                        datetime.strptime(match['timestamp'], '%Y-%m-%dT%H%M%S'),
                        int(match['sequence']), path.stat().st_mtime_ns, path))
            return max(candidates, key=lambda item: item[:3])[3] if candidates else None
        except (OSError, ValueError):
            return None

    def _consume_line(self, raw_line: bytes) -> None:
        try:
            record = json.loads(raw_line.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return
        if not isinstance(record, dict):
            return
        event = record.get('event')
        if event not in ('Location', 'FSDJump'):
            return
        system = record.get('StarSystem')
        if not isinstance(system, str) or not system.strip():
            return
        body = record.get('Body')
        if not isinstance(body, str) or not body.strip():
            body = self._identity.body if self._identity else None
        self._identity = JournalIdentity(system=system.strip(), body=body)
