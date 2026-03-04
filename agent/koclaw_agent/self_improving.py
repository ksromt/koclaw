"""Self-improving learning system for the Koclaw agent.

Tracks learnings (LRN), errors (ERR), and feedback (FBK) in structured
markdown files.  High-value entries are auto-promoted to a persistent
knowledge base that augments the agent's system prompt.

Key design decisions:
  - One asyncio.Lock per target file to allow concurrent writes to
    different files without global contention.
  - Pattern-key counting stored in-memory (rebuilt from log files on
    first access) to decide when a recurring pattern warrants promotion.
  - Promotion size cap (8 KB / ~2000 tokens) prevents the local
    learnings file from bloating the context window.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger

# Entry type -> target filename mapping
_TYPE_FILE_MAP: dict[str, str] = {
    "LRN": "LEARNINGS.md",
    "ERR": "ERRORS.md",
    "FBK": "FEEDBACK.md",
}

# Maximum character length for a single promoted entry
_MAX_PROMO_ENTRY_CHARS = 200

# Maximum total size (chars) for .agent-learnings-local.md
_MAX_LOCAL_LEARNINGS_SIZE = 8000

# Number of identical pattern-key occurrences that trigger auto-promotion
_PATTERN_REPEAT_THRESHOLD = 3

# Characters to strip from promoted content (markdown formatting)
_SANITIZE_RE = re.compile(r"[#*_\[\]`]")


# ── Multilingual correction keywords ──
# Each tuple: (compiled regex, description).
# Patterns are anchored to the start of message OR after common punctuation
# (comma, period, ellipsis, exclamation, question mark, colon, space after CJK punct).

_CN_CORRECTIONS = [
    "不对", "不是", "错了", "搞错了", "说错了", "不是这个意思",
]
_JP_CORRECTIONS = [
    "違う", "間違い", "そうじゃない", "ちがう",
]
_EN_CORRECTIONS = [
    "that's wrong", "that's incorrect", "not what i meant", "that's not right",
]


def _build_correction_pattern() -> re.Pattern:
    """Build a single compiled regex covering all correction keywords.

    Matches when the keyword appears at the very start of the message OR
    immediately after common sentence-boundary punctuation (to handle
    "hmm, that's wrong" or "嗯...不对").

    The pattern is designed to reduce false positives by refusing to
    match keywords buried in the middle of a clause.
    """
    all_keywords: list[str] = []
    all_keywords.extend(_CN_CORRECTIONS)
    all_keywords.extend(_JP_CORRECTIONS)
    all_keywords.extend(_EN_CORRECTIONS)

    # Escape regex-special characters in keywords and sort longest-first
    # so "不是这个意思" matches before "不是"
    escaped = sorted((re.escape(k) for k in all_keywords), key=len, reverse=True)
    alternatives = "|".join(escaped)

    # Match at start of string, or after punctuation + optional whitespace.
    # The punctuation set covers: comma, period, ellipsis (... or \u2026),
    # exclamation, question, CJK punct (\u3001\u3002\uff0c\uff01\uff1f),
    # colon, semicolon, and dash.
    punct = r"[,.\u2026!?\u3001\u3002\uff0c\uff01\uff1f:;\-]"

    pattern = rf"(?:^|{punct}+\s*)(?:{alternatives})"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


_CORRECTION_RE = _build_correction_pattern()


def _sanitize_for_prompt(text: str) -> str:
    """Strip markdown formatting and newlines from text for safe prompt injection.

    Removes: # * _ [ ] ` and replaces newlines with spaces.
    This ensures promoted content is plain text only, preventing
    accidental markdown rendering or prompt structure breakage.
    """
    text = _SANITIZE_RE.sub("", text)
    text = text.replace("\n", " ").replace("\r", " ")
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


@dataclass
class LearningEntry:
    """A single learning / error / feedback record."""

    entry_type: str          # LRN, ERR, or FBK
    priority: str            # critical, high, medium, low
    area: str                # domain area (e.g., "security", "build")
    source: str              # "user", "auto", "admin"
    summary: str
    details: str
    action: str
    related_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    pattern_key: str = ""
    permission: str = "Authenticated"


class SelfImproving:
    """Self-improving learning engine.

    Manages structured learning logs, multilingual correction detection,
    auto-promotion of recurring or critical patterns, and a cached
    loader for injecting learnings into the LLM system prompt.
    """

    def __init__(
        self,
        learnings_dir: str = "workspace/learnings",
        knowledge_dir: str = "workspace/knowledge",
    ) -> None:
        self._learnings_dir = Path(learnings_dir)
        self._knowledge_dir = Path(knowledge_dir)

        # Per-file asyncio locks for concurrent write safety
        self._locks: dict[str, asyncio.Lock] = {}

        # In-memory counter for pattern-key occurrences
        self._pattern_counts: dict[str, int] = {}
        self._pattern_counts_initialized = False

        # ID counter per entry-type per date (e.g., "LRN-20260304" -> next_seq)
        self._id_counters: dict[str, int] = {}

        # Cache for load_learnings()
        self._cache_content: str = ""
        self._cache_mtimes: dict[str, float] = {}

        logger.debug(
            f"SelfImproving initialized: learnings={self._learnings_dir}, "
            f"knowledge={self._knowledge_dir}"
        )

    # ── Internal helpers ──

    def _lock_for(self, key: str) -> asyncio.Lock:
        """Return (or create) an asyncio.Lock keyed by ``key``.

        Thread-safety note: this method is safe without additional
        synchronization because asyncio is single-threaded. There is no
        ``await`` between the dict lookup and the assignment, so no other
        coroutine can interleave between the check and the set.
        """
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _scan_highest_seq(self, entry_type: str, date_str: str) -> int:
        """Scan target files for the highest existing sequence number.

        This prevents duplicate IDs after a process restart by reading
        the on-disk state rather than relying solely on in-memory counters.
        Returns the highest found sequence number, or 0 if none found.
        """
        target_file = _TYPE_FILE_MAP.get(entry_type)
        if target_file is None:
            return 0

        path = self._learnings_dir / target_file
        if not path.exists():
            return 0

        # Pattern: ### TYPE-YYYYMMDD-NNN
        pattern = re.compile(rf"^### {re.escape(entry_type)}-{re.escape(date_str)}-(\d{{3}})")
        highest = 0
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                m = pattern.match(line)
                if m:
                    seq = int(m.group(1))
                    if seq > highest:
                        highest = seq
        except OSError:
            pass
        return highest

    def _next_entry_id(self, entry_type: str) -> str:
        """Generate the next entry ID: TYPE-YYYYMMDD-XXX.

        On first call for a given type+date, scans the existing target
        file for the highest sequence number to avoid ID collisions
        after process restart.
        """
        date_str = datetime.now().strftime("%Y%m%d")
        counter_key = f"{entry_type}-{date_str}"

        if counter_key not in self._id_counters:
            # First call for this key: scan existing file
            self._id_counters[counter_key] = self._scan_highest_seq(
                entry_type, date_str
            )

        seq = self._id_counters[counter_key] + 1
        self._id_counters[counter_key] = seq
        return f"{entry_type}-{date_str}-{seq:03d}"

    def _rebuild_pattern_counts(self) -> None:
        """Scan existing learning files and rebuild in-memory pattern counts.

        Called on first access to ensure pattern counts survive process
        restarts. Reads all log files and counts ``**Pattern**: <key>``
        occurrences.
        """
        if self._pattern_counts_initialized:
            return

        pattern_re = re.compile(r"^- \*\*Pattern\*\*: (.+)$")
        for filename in _TYPE_FILE_MAP.values():
            path = self._learnings_dir / filename
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    m = pattern_re.match(line.strip())
                    if m:
                        key = m.group(1).strip()
                        self._pattern_counts[key] = (
                            self._pattern_counts.get(key, 0) + 1
                        )
            except OSError:
                pass

        self._pattern_counts_initialized = True
        logger.debug(f"Rebuilt pattern counts: {len(self._pattern_counts)} keys")

    @staticmethod
    def _format_entry(entry: LearningEntry, entry_id: str) -> str:
        """Format a LearningEntry as a markdown block."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"### {entry_id}",
            f"- **Time**: {now}",
            f"- **Status**: pending",
            f"- **Priority**: {entry.priority}",
            f"- **Area**: {entry.area}",
            f"- **Source**: {entry.source}",
            f"- **Summary**: {entry.summary}",
            f"- **Details**: {entry.details}",
            f"- **Action**: {entry.action}",
        ]
        if entry.related_files:
            lines.append(f"- **Files**: {', '.join(entry.related_files)}")
        if entry.tags:
            lines.append(f"- **Tags**: {', '.join(entry.tags)}")
        if entry.pattern_key:
            lines.append(f"- **Pattern**: {entry.pattern_key}")
        lines.append("")  # trailing newline
        return "\n".join(lines)

    # ── Public API ──

    async def log_learning(self, entry: LearningEntry) -> str:
        """Append a structured learning entry to the appropriate markdown file.

        Auto-creates directories as needed.  Returns the generated entry ID.
        """
        target_file = _TYPE_FILE_MAP.get(entry.entry_type)
        if target_file is None:
            raise ValueError(f"Unknown entry_type: {entry.entry_type}")

        # Rebuild pattern counts from disk on first access
        self._rebuild_pattern_counts()

        entry_id = self._next_entry_id(entry.entry_type)
        formatted = self._format_entry(entry, entry_id)

        lock = self._lock_for(target_file)
        async with lock:
            self._learnings_dir.mkdir(parents=True, exist_ok=True)
            path = self._learnings_dir / target_file

            # Append to existing file or create with header
            if path.exists():
                existing = path.read_text(encoding="utf-8")
            else:
                header = f"# {entry.entry_type} Log\n\n"
                existing = header

            existing += formatted + "\n"
            path.write_text(existing, encoding="utf-8")

        # Track pattern-key count
        if entry.pattern_key:
            self._pattern_counts[entry.pattern_key] = (
                self._pattern_counts.get(entry.pattern_key, 0) + 1
            )

        logger.info(f"Logged {entry.entry_type} entry: {entry_id}")
        return entry_id

    def detect_correction(self, user_msg: str, bot_msg: str) -> bool:
        """Detect whether the user is correcting the bot's previous response.

        Uses position-aware multilingual keyword matching to reduce false
        positives.  Returns True if a correction pattern is detected.

        This method is synchronous because it performs no I/O — only
        in-memory regex matching.
        """
        if not user_msg or not bot_msg:
            return False

        match = _CORRECTION_RE.search(user_msg)
        if match is None:
            return False

        # Position check: the match must start within the first ~30 characters
        # of the message (or right after leading punctuation/filler).
        # This prevents "他说的不对你觉得呢" from triggering when "不对" is at pos 3
        # after a non-punctuation character.
        start = match.start()
        prefix = user_msg[:start]

        # If there is a non-trivial prefix (more than just whitespace/punct/
        # short filler), it is likely a false positive.
        # Allow: empty prefix, whitespace, or punctuation-only prefix.
        stripped_prefix = re.sub(
            r"[\s,.\u2026!?\u3001\u3002\uff0c\uff01\uff1f:;\-\u3000]+", "", prefix
        )

        # Allow up to 5 CJK/Latin filler characters (e.g., "嗯", "hmm", "あの")
        if len(stripped_prefix) > 5:
            return False

        return True

    async def auto_promote(self, entry: LearningEntry, entry_id: str) -> bool:
        """Check promotion criteria and promote if met.

        Criteria:
          1. Permission gating: Public channel entries are NEVER promoted.
          2. Critical priority -> immediate promotion.
          3. Same pattern_key seen 3+ times -> promotion.
          4. Size limit: .agent-learnings-local.md must stay under 8000 chars.

        Returns True if the entry was promoted.
        """
        # Rule 1: Public channel NEVER auto-promotes
        if entry.permission == "Public":
            logger.debug(f"Promotion denied for {entry_id}: Public permission")
            return False

        # Determine if promotion criteria are met
        should_promote = False
        promotion_reason = ""

        # Rule 2: Critical priority
        if entry.priority == "critical":
            should_promote = True
            promotion_reason = "critical priority"
            logger.debug(f"Promotion triggered for {entry_id}: critical priority")

        # Rule 3: Pattern-key repetition
        if (
            not should_promote
            and entry.pattern_key
            and self._pattern_counts.get(entry.pattern_key, 0)
                >= _PATTERN_REPEAT_THRESHOLD
        ):
            should_promote = True
            count = self._pattern_counts[entry.pattern_key]
            promotion_reason = (
                f"{count}x repeated (pattern: {entry.pattern_key})"
            )
            logger.debug(
                f"Promotion triggered for {entry_id}: pattern "
                f"'{entry.pattern_key}' seen {count} times"
            )

        if not should_promote:
            return False

        # Sanitize: strip markdown formatting and newlines, then truncate
        sanitized_summary = _sanitize_for_prompt(
            entry.summary[:_MAX_PROMO_ENTRY_CHARS]
        )
        promo_line = (
            f"- [{entry_id}] ({entry.area}) {sanitized_summary}"
        )

        # Write to .agent-learnings-local.md (size check inside lock)
        self._knowledge_dir.mkdir(parents=True, exist_ok=True)
        local_file = self._knowledge_dir / ".agent-learnings-local.md"

        lock = self._lock_for(".agent-learnings-local.md")
        async with lock:
            # Rule 4: Size limit check (inside lock to prevent races)
            current_size = 0
            if local_file.exists():
                content = local_file.read_text(encoding="utf-8")
                current_size = len(content)
            else:
                content = ""

            if current_size >= _MAX_LOCAL_LEARNINGS_SIZE:
                logger.warning(
                    f"Promotion blocked for {entry_id}: local learnings "
                    f"size {current_size} >= {_MAX_LOCAL_LEARNINGS_SIZE}"
                )
                return False

            content += promo_line + "\n"
            local_file.write_text(content, encoding="utf-8")

        # Record the promotion in PROMOTIONS.md (structured format)
        timestamp = datetime.now().strftime("%Y-%m-%d")
        promo_id = f"PROMO-{timestamp}-{entry_id.split('-')[-1]}"
        promo_record = (
            f"### [{promo_id}]\n"
            f"- **Time**: {timestamp}\n"
            f"- **Source entries**: {entry_id}\n"
            f"- **Target**: .agent-learnings-local.md\n"
            f"- **Content**: {sanitized_summary}\n"
            f"- **Reason**: {promotion_reason}\n"
            f"- **Status**: active\n\n"
        )

        promo_lock = self._lock_for("PROMOTIONS.md")
        async with promo_lock:
            self._learnings_dir.mkdir(parents=True, exist_ok=True)
            promo_path = self._learnings_dir / "PROMOTIONS.md"
            if promo_path.exists():
                promo_content = promo_path.read_text(encoding="utf-8")
            else:
                promo_content = "# Promotion Log\n\n"
            promo_content += promo_record
            promo_path.write_text(promo_content, encoding="utf-8")

        logger.info(f"Promoted {entry_id} -> {promo_id}")
        return True

    async def revoke_promotion(
        self, promo_id: str, confirmed: bool = False
    ) -> dict:
        """Revoke a previously promoted entry.

        If `confirmed` is False, returns a confirmation prompt.
        If `confirmed` is True, removes the entry from
        .agent-learnings-local.md and marks it revoked in PROMOTIONS.md.
        """
        if not confirmed:
            return {
                "status": "pending_confirmation",
                "promo_id": promo_id,
                "message": (
                    f"Please confirm revocation of {promo_id}. "
                    f"This will remove the entry from the active learnings."
                ),
            }

        # Look up source entry ID from PROMOTIONS.md
        promo_path = self._learnings_dir / "PROMOTIONS.md"
        if not promo_path.exists():
            return {"status": "error", "message": f"No PROMOTIONS.md file found"}

        # Find the source entries for this promo_id
        entry_id = None
        promo_lock = self._lock_for("PROMOTIONS.md")
        async with promo_lock:
            promo_content = promo_path.read_text(encoding="utf-8")

            # Check if promo_id exists in the file
            if promo_id not in promo_content:
                return {
                    "status": "error",
                    "message": f"Promotion {promo_id} not found in PROMOTIONS.md",
                }

            # Extract source entry ID from the structured block
            source_re = re.compile(
                rf"### \[{re.escape(promo_id)}\]\n"
                r"(?:- \*\*\w+\*\*:.*\n)*?"
                r"- \*\*Source entries\*\*: (\S+)"
            )
            source_match = source_re.search(promo_content)
            if source_match:
                entry_id = source_match.group(1)

            # Mark as revoked: change Status: active -> Status: revoked
            # Find the status line in the block for this promo_id
            promo_content = re.sub(
                rf"(### \[{re.escape(promo_id)}\].*?- \*\*Status\*\*: )active",
                r"\1revoked",
                promo_content,
                flags=re.DOTALL,
            )
            promo_path.write_text(promo_content, encoding="utf-8")

        if entry_id is None:
            return {
                "status": "error",
                "message": f"Could not extract source entry from {promo_id}",
            }

        # Remove from .agent-learnings-local.md
        local_file = self._knowledge_dir / ".agent-learnings-local.md"
        if not local_file.exists():
            return {"status": "error", "message": "No local learnings file found"}

        lock = self._lock_for(".agent-learnings-local.md")
        async with lock:
            content = local_file.read_text(encoding="utf-8")
            lines = content.split("\n")
            new_lines = [
                line for line in lines
                if not (line.startswith("- [") and f"[{entry_id}]" in line)
            ]
            new_content = "\n".join(new_lines)

            if new_content == content:
                return {
                    "status": "error",
                    "message": f"Entry {entry_id} not found in local learnings",
                }

            local_file.write_text(new_content, encoding="utf-8")

        logger.info(f"Revoked promotion: {promo_id}")
        return {"status": "revoked", "promo_id": promo_id}

    async def load_learnings(self) -> str:
        """Load learnings from both baseline and local files.

        Reads:
          - agent-learnings.md  (hand-curated baseline)
          - .agent-learnings-local.md  (auto-promoted entries)

        Results are cached by file mtime for efficiency.  Returns the
        combined content wrapped in a section header, or empty string if
        no learnings exist.
        """
        if not self._knowledge_dir.exists():
            return ""

        baseline_path = self._knowledge_dir / "agent-learnings.md"
        local_path = self._knowledge_dir / ".agent-learnings-local.md"

        # Check mtimes to determine if cache is valid
        current_mtimes: dict[str, float] = {}
        for p in [baseline_path, local_path]:
            if p.exists():
                current_mtimes[str(p)] = p.stat().st_mtime

        if current_mtimes == self._cache_mtimes and self._cache_content:
            return self._cache_content

        parts: list[str] = []

        # Load baseline (strip markdown headers)
        if baseline_path.exists():
            content = baseline_path.read_text(encoding="utf-8")
            # Strip lines that are markdown headers (# ...)
            lines = content.split("\n")
            stripped = [
                line for line in lines
                if not re.match(r"^#{1,6}\s", line)
            ]
            baseline_text = "\n".join(stripped).strip()
            if baseline_text:
                parts.append(baseline_text)

        # Load local (auto-promoted, no stripping needed)
        if local_path.exists():
            content = local_path.read_text(encoding="utf-8")
            content = content.strip()
            if content:
                parts.append(content)

        if not parts:
            self._cache_content = ""
            self._cache_mtimes = current_mtimes
            return ""

        combined = "\n\n".join(parts)
        result = f"## Learned Patterns (auto-generated)\n\n{combined}"

        # Update cache
        self._cache_content = result
        self._cache_mtimes = current_mtimes

        return result
