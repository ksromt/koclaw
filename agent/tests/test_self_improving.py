"""Tests for the self-improving learning system."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from koclaw_agent.self_improving import LearningEntry, SelfImproving, _sanitize_for_prompt


# ── Fixtures ──


@pytest.fixture
def learnings_dir(tmp_path: Path) -> Path:
    return tmp_path / "learnings"


@pytest.fixture
def knowledge_dir(tmp_path: Path) -> Path:
    return tmp_path / "knowledge"


@pytest.fixture
def si(learnings_dir: Path, knowledge_dir: Path) -> SelfImproving:
    return SelfImproving(
        learnings_dir=str(learnings_dir),
        knowledge_dir=str(knowledge_dir),
    )


@pytest.fixture
def sample_learning() -> LearningEntry:
    return LearningEntry(
        entry_type="LRN",
        priority="medium",
        area="testing",
        source="user",
        summary="pytest fixtures should use tmp_path",
        details="Using tmp_path ensures test isolation",
        action="Always use tmp_path for filesystem tests",
        related_files=["tests/test_self_improving.py"],
        tags=["testing", "pytest"],
        pattern_key="pytest-tmpdir",
    )


@pytest.fixture
def sample_error() -> LearningEntry:
    return LearningEntry(
        entry_type="ERR",
        priority="high",
        area="deployment",
        source="auto",
        summary="Port already in use on restart",
        details="Gateway fails to bind 18790 if previous instance still running",
        action="Kill old process before starting",
        related_files=["gateway/src/main.rs"],
        tags=["deployment", "port"],
        pattern_key="port-conflict",
    )


@pytest.fixture
def sample_feedback() -> LearningEntry:
    return LearningEntry(
        entry_type="FBK",
        priority="medium",
        area="persona",
        source="user",
        summary="Responses too formal in casual chat",
        details="User prefers more casual tone in Telegram",
        action="Adjust persona prompt for Telegram channel",
        related_files=["persona.yaml"],
        tags=["persona", "tone"],
        pattern_key="tone-casual",
    )


# ── TestLogLearning ──


class TestLogLearning:
    """Tests for log_learning functionality."""

    @pytest.mark.asyncio
    async def test_log_learning_creates_file(
        self, si: SelfImproving, sample_learning: LearningEntry, learnings_dir: Path
    ):
        """log_learning should create the appropriate markdown file."""
        entry_id = await si.log_learning(sample_learning)
        assert entry_id.startswith("LRN-")
        learnings_file = learnings_dir / "LEARNINGS.md"
        assert learnings_file.exists()

    @pytest.mark.asyncio
    async def test_log_error_creates_errors_file(
        self, si: SelfImproving, sample_error: LearningEntry, learnings_dir: Path
    ):
        """ERR entries go to ERRORS.md."""
        entry_id = await si.log_learning(sample_error)
        assert entry_id.startswith("ERR-")
        errors_file = learnings_dir / "ERRORS.md"
        assert errors_file.exists()

    @pytest.mark.asyncio
    async def test_log_feedback_creates_feedback_file(
        self, si: SelfImproving, sample_feedback: LearningEntry, learnings_dir: Path
    ):
        """FBK entries go to FEEDBACK.md."""
        entry_id = await si.log_learning(sample_feedback)
        assert entry_id.startswith("FBK-")
        feedback_file = learnings_dir / "FEEDBACK.md"
        assert feedback_file.exists()

    @pytest.mark.asyncio
    async def test_entry_id_format(
        self, si: SelfImproving, sample_learning: LearningEntry
    ):
        """Entry ID must follow TYPE-YYYYMMDD-XXX format."""
        entry_id = await si.log_learning(sample_learning)
        pattern = r"^LRN-\d{8}-\d{3}$"
        assert re.match(pattern, entry_id), f"Entry ID '{entry_id}' doesn't match format"

    @pytest.mark.asyncio
    async def test_entry_id_auto_increments(
        self, si: SelfImproving, sample_learning: LearningEntry
    ):
        """Multiple entries on same day should auto-increment the counter."""
        id1 = await si.log_learning(sample_learning)
        id2 = await si.log_learning(sample_learning)
        id3 = await si.log_learning(sample_learning)
        # Extract counter parts
        counter1 = int(id1.split("-")[-1])
        counter2 = int(id2.split("-")[-1])
        counter3 = int(id3.split("-")[-1])
        assert counter2 == counter1 + 1
        assert counter3 == counter2 + 1

    @pytest.mark.asyncio
    async def test_init_creates_directories(
        self, si: SelfImproving, learnings_dir: Path, knowledge_dir: Path
    ):
        """__init__ should eagerly create learnings and knowledge directories."""
        assert learnings_dir.exists()
        assert knowledge_dir.exists()

    @pytest.mark.asyncio
    async def test_log_content_includes_fields(
        self, si: SelfImproving, sample_learning: LearningEntry, learnings_dir: Path
    ):
        """Written markdown should contain entry fields."""
        await si.log_learning(sample_learning)
        content = (learnings_dir / "LEARNINGS.md").read_text(encoding="utf-8")
        assert "pytest fixtures should use tmp_path" in content
        assert "testing" in content
        assert "pytest-tmpdir" in content

    @pytest.mark.asyncio
    async def test_log_content_includes_time_and_status(
        self, si: SelfImproving, sample_learning: LearningEntry, learnings_dir: Path
    ):
        """Written markdown should include Time and Status fields."""
        await si.log_learning(sample_learning)
        content = (learnings_dir / "LEARNINGS.md").read_text(encoding="utf-8")
        assert "**Time**:" in content
        assert "**Status**: pending" in content
        # Verify time format (YYYY-MM-DD HH:MM)
        time_match = re.search(r"\*\*Time\*\*: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", content)
        assert time_match, "Time field should be in YYYY-MM-DD HH:MM format"

    @pytest.mark.asyncio
    async def test_concurrent_writes(
        self, si: SelfImproving, learnings_dir: Path
    ):
        """Concurrent writes should not corrupt the file."""
        entries = [
            LearningEntry(
                entry_type="LRN",
                priority="medium",
                area="test",
                source="auto",
                summary=f"Concurrent entry {i}",
                details=f"Detail {i}",
                action=f"Action {i}",
                related_files=[],
                tags=["concurrent"],
                pattern_key=f"concurrent-{i}",
            )
            for i in range(10)
        ]
        ids = await asyncio.gather(*(si.log_learning(e) for e in entries))
        # All IDs should be unique
        assert len(set(ids)) == 10
        # File should contain all entries
        content = (learnings_dir / "LEARNINGS.md").read_text(encoding="utf-8")
        for i in range(10):
            assert f"Concurrent entry {i}" in content

    @pytest.mark.asyncio
    async def test_multiple_entry_types_separate_files(
        self,
        si: SelfImproving,
        sample_learning: LearningEntry,
        sample_error: LearningEntry,
        sample_feedback: LearningEntry,
        learnings_dir: Path,
    ):
        """Different entry types write to different files."""
        await si.log_learning(sample_learning)
        await si.log_learning(sample_error)
        await si.log_learning(sample_feedback)
        assert (learnings_dir / "LEARNINGS.md").exists()
        assert (learnings_dir / "ERRORS.md").exists()
        assert (learnings_dir / "FEEDBACK.md").exists()


# ── TestDetectCorrection ──


class TestDetectCorrection:
    """Tests for multilingual correction detection."""

    def test_chinese_correction_start(self, si: SelfImproving):
        """Chinese correction keywords at start of message."""
        assert si.detect_correction("不对，应该是这样的", "之前的回答")
        assert si.detect_correction("错了，不是A而是B", "A是正确答案")
        assert si.detect_correction("搞错了，我说的是X", "Y")
        assert si.detect_correction("说错了吧", "之前说的")
        assert si.detect_correction("不是这个意思，我要的是...", "你要说的是...")

    def test_japanese_correction_start(self, si: SelfImproving):
        """Japanese correction keywords at start of message."""
        assert si.detect_correction("違う、そっちじゃなくて", "前の回答")
        assert si.detect_correction("間違いだよ、正しくは...", "前の回答")
        assert si.detect_correction("そうじゃない、こっちだよ", "前の回答")
        assert si.detect_correction("ちがう、それは間違い", "前の回答")

    def test_english_correction_start(self, si: SelfImproving):
        """English correction keywords at start of message."""
        assert si.detect_correction("that's wrong, it should be X", "prev response")
        assert si.detect_correction("that's incorrect, the answer is Y", "prev")
        assert si.detect_correction("not what I meant, I was asking about Z", "prev")
        assert si.detect_correction("that's not right, try again", "prev")

    def test_correction_after_punctuation(self, si: SelfImproving):
        """Correction keywords appearing after punctuation (not just at start)."""
        assert si.detect_correction("嗯...不对，重新来", "回答")
        assert si.detect_correction("hmm, that's wrong, try again", "response")
        assert si.detect_correction("あの...違う、そうじゃなくて", "回答")

    def test_false_positive_resistance_cn(self, si: SelfImproving):
        """Chinese: keywords embedded mid-sentence should NOT trigger."""
        # "Not right" embedded in a longer context about something else
        assert not si.detect_correction("他说的不对你觉得呢", "回答")
        assert not si.detect_correction("这个问题很不是我想的那样", "回答")

    def test_false_positive_resistance_en(self, si: SelfImproving):
        """English: keywords buried in the middle should NOT trigger."""
        assert not si.detect_correction(
            "I think the documentation says that's wrong approach for beginners", "response"
        )

    def test_false_positive_resistance_jp(self, si: SelfImproving):
        """Japanese: embedded keywords should NOT trigger."""
        assert not si.detect_correction("彼の意見は違うと思う", "回答")

    def test_empty_messages(self, si: SelfImproving):
        """Empty messages should never detect correction."""
        assert not si.detect_correction("", "response")
        assert not si.detect_correction("hello", "")

    def test_no_correction_normal_chat(self, si: SelfImproving):
        """Normal conversation should not trigger correction detection."""
        assert not si.detect_correction("Thanks, that's helpful!", "response")
        assert not si.detect_correction("ありがとう、助かった", "回答")
        assert not si.detect_correction("好的，谢谢你", "回答")


# ── TestAutoPromote ──


class TestAutoPromote:
    """Tests for auto-promotion to persistent learnings."""

    @pytest.mark.asyncio
    async def test_critical_priority_promotes(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Critical priority entries should auto-promote."""
        entry = LearningEntry(
            entry_type="ERR",
            priority="critical",
            area="security",
            source="auto",
            summary="XSS vulnerability in chat input",
            details="Unsanitized input allows script injection",
            action="Sanitize all user input before rendering",
            related_files=["sdk/src/widget.ts"],
            tags=["security", "xss"],
            pattern_key="xss-input",
        )
        entry_id = await si.log_learning(entry)
        promoted = await si.auto_promote(entry, entry_id)
        assert promoted is True
        # Check the local learnings file was created
        local_learnings = knowledge_dir / ".agent-learnings-local.md"
        assert local_learnings.exists()
        content = local_learnings.read_text(encoding="utf-8")
        assert "XSS vulnerability" in content

    @pytest.mark.asyncio
    async def test_public_permission_never_promotes(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Public channel entries should never be auto-promoted."""
        entry = LearningEntry(
            entry_type="LRN",
            priority="critical",
            area="security",
            source="auto",
            summary="Important but from public channel",
            details="Details here",
            action="Action here",
            related_files=[],
            tags=[],
            pattern_key="public-test",
            permission="Public",
        )
        entry_id = await si.log_learning(entry)
        promoted = await si.auto_promote(entry, entry_id)
        assert promoted is False

    @pytest.mark.asyncio
    async def test_pattern_key_three_times_promotes(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Same pattern_key occurring 3+ times should trigger promotion."""
        for i in range(3):
            entry = LearningEntry(
                entry_type="ERR",
                priority="medium",
                area="build",
                source="auto",
                summary=f"Build failure variant {i}",
                details=f"Detail {i}",
                action="Fix the build",
                related_files=[],
                tags=["build"],
                pattern_key="build-failure-repeated",
            )
            entry_id = await si.log_learning(entry)
            promoted = await si.auto_promote(entry, entry_id)
            if i < 2:
                assert promoted is False
            else:
                # Third occurrence should trigger promotion
                assert promoted is True

    @pytest.mark.asyncio
    async def test_promotion_sanitizes_content(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Promoted entries should have markdown formatting stripped."""
        entry = LearningEntry(
            entry_type="LRN",
            priority="critical",
            area="test",
            source="auto",
            summary="Use **bold** and `code` and [links](url) in # summary",
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="sanitize-test",
        )
        entry_id = await si.log_learning(entry)
        await si.auto_promote(entry, entry_id)
        local_learnings = knowledge_dir / ".agent-learnings-local.md"
        content = local_learnings.read_text(encoding="utf-8")
        # Markdown chars should be stripped
        assert "**" not in content
        assert "`code`" not in content
        assert "[links]" not in content
        # But the plain text should remain
        assert "bold" in content
        assert "code" in content

    @pytest.mark.asyncio
    async def test_promotion_sanitizes_length(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Promoted entries should be truncated to max 200 chars."""
        long_summary = "A" * 300
        entry = LearningEntry(
            entry_type="LRN",
            priority="critical",
            area="test",
            source="auto",
            summary=long_summary,
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="long-summary",
        )
        entry_id = await si.log_learning(entry)
        await si.auto_promote(entry, entry_id)
        local_learnings = knowledge_dir / ".agent-learnings-local.md"
        content = local_learnings.read_text(encoding="utf-8")
        # No single line should exceed 200 chars of promoted content
        for line in content.split("\n"):
            if line.startswith("- "):
                # The promoted summary line
                assert len(line) <= 250  # some overhead for formatting

    @pytest.mark.asyncio
    async def test_promotion_respects_size_limit(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Promotions should stop when .agent-learnings-local.md reaches 8000 chars."""
        # Pre-fill the file to near the limit
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        local_file = knowledge_dir / ".agent-learnings-local.md"
        local_file.write_text("X" * 8000, encoding="utf-8")

        entry = LearningEntry(
            entry_type="LRN",
            priority="critical",
            area="test",
            source="auto",
            summary="This should not be promoted due to size limit",
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="size-limit-test",
        )
        entry_id = await si.log_learning(entry)
        promoted = await si.auto_promote(entry, entry_id)
        assert promoted is False

    @pytest.mark.asyncio
    async def test_promotion_writes_structured_promotions_md(
        self, si: SelfImproving, learnings_dir: Path
    ):
        """Each promotion should be recorded in PROMOTIONS.md with structured format."""
        entry = LearningEntry(
            entry_type="ERR",
            priority="critical",
            area="test",
            source="auto",
            summary="Critical error to promote",
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="promo-record-test",
        )
        entry_id = await si.log_learning(entry)
        await si.auto_promote(entry, entry_id)
        promo_file = learnings_dir / "PROMOTIONS.md"
        assert promo_file.exists()
        content = promo_file.read_text(encoding="utf-8")
        # Check structured format fields
        assert entry_id in content
        assert "**Source entries**:" in content
        assert "**Target**: .agent-learnings-local.md" in content
        assert "**Content**:" in content
        assert "**Reason**:" in content
        assert "**Status**: active" in content
        assert "### [PROMO-" in content

    @pytest.mark.asyncio
    async def test_medium_priority_does_not_promote_without_repeats(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Medium priority with unique pattern_key should not promote."""
        entry = LearningEntry(
            entry_type="LRN",
            priority="medium",
            area="test",
            source="auto",
            summary="A medium learning",
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="unique-pattern-no-repeat",
        )
        entry_id = await si.log_learning(entry)
        promoted = await si.auto_promote(entry, entry_id)
        assert promoted is False


# ── TestRevokePromotion ──


class TestRevokePromotion:
    """Tests for promotion revocation."""

    @pytest.mark.asyncio
    async def test_revoke_without_confirmation_returns_prompt(
        self, si: SelfImproving, knowledge_dir: Path, learnings_dir: Path
    ):
        """Revoking without confirmed=True should return a confirmation prompt."""
        # First promote something
        entry = LearningEntry(
            entry_type="LRN",
            priority="critical",
            area="test",
            source="auto",
            summary="Entry to revoke",
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="revoke-test",
        )
        entry_id = await si.log_learning(entry)
        await si.auto_promote(entry, entry_id)

        # Get promo_id from PROMOTIONS.md
        promo_content = (learnings_dir / "PROMOTIONS.md").read_text(encoding="utf-8")
        promo_match = re.search(r"### \[(PROMO-\S+?)\]", promo_content)
        assert promo_match, "No promo ID found in PROMOTIONS.md"
        promo_id = promo_match.group(1)

        result = await si.revoke_promotion(promo_id, confirmed=False)
        assert result["status"] == "pending_confirmation"
        assert "confirm" in result.get("message", "").lower() or "promo_id" in result

    @pytest.mark.asyncio
    async def test_revoke_with_confirmation_removes_entry(
        self, si: SelfImproving, knowledge_dir: Path, learnings_dir: Path
    ):
        """Revoking with confirmed=True should remove from local learnings."""
        entry = LearningEntry(
            entry_type="LRN",
            priority="critical",
            area="test",
            source="auto",
            summary="Entry to actually revoke",
            details="details",
            action="action",
            related_files=[],
            tags=[],
            pattern_key="revoke-confirmed-test",
        )
        entry_id = await si.log_learning(entry)
        await si.auto_promote(entry, entry_id)

        # Verify it was promoted
        local_file = knowledge_dir / ".agent-learnings-local.md"
        assert "Entry to actually revoke" in local_file.read_text(encoding="utf-8")

        # Get promo_id from structured PROMOTIONS.md
        promo_content = (learnings_dir / "PROMOTIONS.md").read_text(encoding="utf-8")
        promo_match = re.search(r"### \[(PROMO-\S+?)\]", promo_content)
        assert promo_match
        promo_id = promo_match.group(1)

        result = await si.revoke_promotion(promo_id, confirmed=True)
        assert result["status"] == "revoked"

        # Entry should be removed from local learnings
        content = local_file.read_text(encoding="utf-8")
        assert "Entry to actually revoke" not in content

        # PROMOTIONS.md should show revoked status
        promo_content = (learnings_dir / "PROMOTIONS.md").read_text(encoding="utf-8")
        assert "**Status**: revoked" in promo_content

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_promo(
        self, si: SelfImproving, learnings_dir: Path
    ):
        """Revoking a non-existent promotion should return error."""
        # Create PROMOTIONS.md so the file exists but without target entry
        learnings_dir.mkdir(parents=True, exist_ok=True)
        (learnings_dir / "PROMOTIONS.md").write_text(
            "# Promotion Log\n\n", encoding="utf-8"
        )
        result = await si.revoke_promotion("PROMO-nonexistent", confirmed=True)
        assert result["status"] == "error"


# ── TestLoadLearnings ──


class TestLoadLearnings:
    """Tests for loading and caching learnings."""

    @pytest.mark.asyncio
    async def test_load_empty(self, si: SelfImproving):
        """Loading with no files should return empty string."""
        result = await si.load_learnings()
        assert result == ""

    @pytest.mark.asyncio
    async def test_load_baseline_file(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Load from agent-learnings.md (baseline)."""
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        baseline = knowledge_dir / "agent-learnings.md"
        baseline.write_text(
            "# Baseline Learnings\n\n- Always validate input\n- Use typed errors\n",
            encoding="utf-8",
        )
        result = await si.load_learnings()
        assert "Always validate input" in result
        assert "Use typed errors" in result
        assert "## Learned Patterns (auto-generated)" in result

    @pytest.mark.asyncio
    async def test_load_local_file(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Load from .agent-learnings-local.md (auto-promoted)."""
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        local_file = knowledge_dir / ".agent-learnings-local.md"
        local_file.write_text(
            "- Sanitize all user input\n- Check file permissions\n",
            encoding="utf-8",
        )
        result = await si.load_learnings()
        assert "Sanitize all user input" in result
        assert "Check file permissions" in result

    @pytest.mark.asyncio
    async def test_load_both_files(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Both baseline and local files should be merged."""
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "agent-learnings.md").write_text(
            "# Learnings\n\n- Baseline rule\n", encoding="utf-8"
        )
        (knowledge_dir / ".agent-learnings-local.md").write_text(
            "- Local rule\n", encoding="utf-8"
        )
        result = await si.load_learnings()
        assert "Baseline rule" in result
        assert "Local rule" in result

    @pytest.mark.asyncio
    async def test_load_strips_markdown_headers_from_baseline(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Baseline headers like '# Title' should be stripped."""
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "agent-learnings.md").write_text(
            "# My Title\n## Subsection\n\n- Rule one\n", encoding="utf-8"
        )
        result = await si.load_learnings()
        assert "# My Title" not in result
        assert "## Subsection" not in result
        assert "Rule one" in result

    @pytest.mark.asyncio
    async def test_caching_uses_mtime(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Subsequent loads should use cached content if mtime unchanged."""
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        baseline = knowledge_dir / "agent-learnings.md"
        baseline.write_text("- First version\n", encoding="utf-8")

        result1 = await si.load_learnings()
        assert "First version" in result1

        # Modify file content without changing mtime (simulate cache hit)
        # On second call with same mtime, should return cached result
        result2 = await si.load_learnings()
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_cache_invalidation_on_change(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Cache should be invalidated when file mtime changes."""
        import time

        knowledge_dir.mkdir(parents=True, exist_ok=True)
        baseline = knowledge_dir / "agent-learnings.md"
        baseline.write_text("- First version\n", encoding="utf-8")

        result1 = await si.load_learnings()
        assert "First version" in result1

        # Small delay to ensure mtime differs
        time.sleep(0.05)
        baseline.write_text("- Updated version\n", encoding="utf-8")

        result2 = await si.load_learnings()
        assert "Updated version" in result2

    @pytest.mark.asyncio
    async def test_load_missing_files_gracefully(
        self, si: SelfImproving, knowledge_dir: Path
    ):
        """Missing knowledge_dir or files should not raise."""
        # knowledge_dir doesn't exist yet
        result = await si.load_learnings()
        assert result == ""


# ── TestSanitization ──


class TestSanitization:
    """Tests for content sanitization helper."""

    def test_strips_markdown_formatting(self):
        """Markdown chars should be removed."""
        text = "Use **bold** and `code` with # heading"
        result = _sanitize_for_prompt(text)
        assert "**" not in result
        assert "`" not in result
        assert "#" not in result
        assert "bold" in result
        assert "code" in result

    def test_strips_newlines(self):
        """Newlines should be replaced with spaces."""
        text = "line one\nline two\rline three"
        result = _sanitize_for_prompt(text)
        assert "\n" not in result
        assert "\r" not in result
        assert "line one line two line three" == result

    def test_strips_brackets(self):
        """Square brackets should be removed."""
        text = "See [link](url) and [ref]"
        result = _sanitize_for_prompt(text)
        assert "[" not in result
        assert "]" not in result

    def test_collapses_multiple_spaces(self):
        """Multiple consecutive spaces should be collapsed."""
        text = "word   with    spaces"
        result = _sanitize_for_prompt(text)
        assert "word with spaces" == result


# ── TestEntryIdScanning ──


class TestEntryIdScanning:
    """Tests for entry ID scanning from existing files (S4)."""

    @pytest.mark.asyncio
    async def test_id_continues_from_existing_file(
        self, si: SelfImproving, learnings_dir: Path
    ):
        """Entry IDs should continue from the highest existing ID in the file."""
        from datetime import datetime

        # Pre-create a file with existing entries
        learnings_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        existing_content = (
            "# LRN Log\n\n"
            f"### LRN-{date_str}-001\n"
            "- **Priority**: medium\n\n"
            f"### LRN-{date_str}-005\n"
            "- **Priority**: high\n\n"
        )
        (learnings_dir / "LEARNINGS.md").write_text(existing_content, encoding="utf-8")

        entry = LearningEntry(
            entry_type="LRN",
            priority="medium",
            area="test",
            source="auto",
            summary="New entry after restart",
            details="details",
            action="action",
        )
        entry_id = await si.log_learning(entry)
        # Should be 006 (after highest existing 005)
        assert entry_id == f"LRN-{date_str}-006"


# ── TestPatternCountRebuild ──


class TestPatternCountRebuild:
    """Tests for pattern count rebuilding from files (S5)."""

    @pytest.mark.asyncio
    async def test_pattern_counts_rebuilt_from_files(
        self, learnings_dir: Path, knowledge_dir: Path
    ):
        """Pattern counts should be rebuilt from existing files on first access."""
        # Pre-create a file with pattern entries
        learnings_dir.mkdir(parents=True, exist_ok=True)
        existing_content = (
            "# ERR Log\n\n"
            "### ERR-20260304-001\n"
            "- **Priority**: high\n"
            "- **Pattern**: port-conflict\n\n"
            "### ERR-20260304-002\n"
            "- **Priority**: high\n"
            "- **Pattern**: port-conflict\n\n"
            "### ERR-20260304-003\n"
            "- **Priority**: medium\n"
            "- **Pattern**: build-failure\n\n"
        )
        (learnings_dir / "ERRORS.md").write_text(existing_content, encoding="utf-8")

        # Create fresh SelfImproving that reads existing files
        si2 = SelfImproving(
            learnings_dir=str(learnings_dir),
            knowledge_dir=str(knowledge_dir),
        )

        # Log a new entry to trigger pattern count rebuild
        entry = LearningEntry(
            entry_type="ERR",
            priority="high",
            area="deployment",
            source="auto",
            summary="Port conflict again",
            details="details",
            action="action",
            pattern_key="port-conflict",
        )
        await si2.log_learning(entry)

        # After rebuild + new entry, port-conflict should be at 3
        assert si2._pattern_counts["port-conflict"] == 3
        assert si2._pattern_counts["build-failure"] == 1
