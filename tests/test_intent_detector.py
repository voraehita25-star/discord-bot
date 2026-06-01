"""
Tests for cogs/ai_core/processing/intent_detector.py

Comprehensive tests for IntentDetector and related classes.
"""


class TestIntentEnum:
    """Tests for Intent enum."""

    def test_intent_greeting(self):
        """Test GREETING intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.GREETING.value == "greeting"

    def test_intent_question(self):
        """Test QUESTION intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.QUESTION.value == "question"

    def test_intent_command(self):
        """Test COMMAND intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.COMMAND.value == "command"

    def test_intent_roleplay(self):
        """Test ROLEPLAY intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.ROLEPLAY.value == "roleplay"

    def test_intent_emotional(self):
        """Test EMOTIONAL intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.EMOTIONAL.value == "emotional"

    def test_intent_casual(self):
        """Test CASUAL intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.CASUAL.value == "casual"

    def test_intent_unknown(self):
        """Test UNKNOWN intent."""
        from cogs.ai_core.processing.intent_detector import Intent

        assert Intent.UNKNOWN.value == "unknown"


class TestIntentResult:
    """Tests for IntentResult dataclass."""

    def test_create_intent_result(self):
        """Test creating IntentResult."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentResult

        result = IntentResult(intent=Intent.GREETING, confidence=0.9)

        assert result.intent == Intent.GREETING
        assert result.confidence == 0.9
        assert result.sub_category is None
        assert result.detected_patterns == []

    def test_intent_result_with_all_fields(self):
        """Test IntentResult with all fields."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentResult

        result = IntentResult(
            intent=Intent.QUESTION,
            confidence=0.85,
            sub_category="thai_question",
            detected_patterns=["thai_question", "question_mark"],
        )

        assert result.intent == Intent.QUESTION
        assert result.confidence == 0.85
        assert result.sub_category == "thai_question"
        assert len(result.detected_patterns) == 2

    def test_intent_result_post_init(self):
        """Test post_init sets empty list."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentResult

        result = IntentResult(intent=Intent.CASUAL, confidence=0.5)

        assert result.detected_patterns == []


class TestIntentDetectorInit:
    """Tests for IntentDetector initialization."""

    def test_init_compiles_patterns(self):
        """Test patterns are compiled on init."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()

        assert detector._compiled_patterns is not None
        assert len(detector._compiled_patterns) > 0

    def test_init_has_logger(self):
        """Test logger is created."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()

        assert detector.logger is not None


class TestIntentDetectorDetect:
    """Tests for detect method."""

    def test_detect_empty_message(self):
        """Test detect with empty message."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("")

        assert result.intent == Intent.UNKNOWN
        assert result.confidence == 0.0

    def test_detect_whitespace_only(self):
        """Test detect with whitespace only."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("   ")

        assert result.intent == Intent.UNKNOWN

    def test_detect_thai_greeting(self):
        """Test detect Thai greeting."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("สวัสดีครับ")

        assert result.intent == Intent.GREETING
        assert result.confidence >= 0.8

    def test_detect_english_greeting(self):
        """Test detect English greeting."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("Hello there!")

        assert result.intent == Intent.GREETING
        assert result.confidence >= 0.8

    def test_detect_thai_question(self):
        """Test detect Thai question."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("นี่คืออะไร?")

        assert result.intent == Intent.QUESTION
        assert result.confidence >= 0.6

    def test_detect_english_question(self):
        """Test detect English question."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("What is this?")

        assert result.intent == Intent.QUESTION
        assert result.confidence >= 0.6

    def test_detect_command_server_management(self):
        """Test detect server management command."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("สร้างห้อง test")

        assert result.intent == Intent.COMMAND
        assert result.confidence >= 0.8

    def test_detect_command_memory(self):
        """Test detect memory command."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("จำไว้ว่าฉันชื่อ John")

        assert result.intent == Intent.COMMAND

    def test_detect_roleplay_character_tag(self):
        """Test detect roleplay with character tag."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("{{Alice}} says hello")

        assert result.intent == Intent.ROLEPLAY
        assert result.confidence >= 0.9

    def test_detect_roleplay_action_marker(self):
        """Test detect roleplay with action marker."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("*walks into the room*")

        assert result.intent == Intent.ROLEPLAY
        assert result.confidence >= 0.8

    def test_detect_emotional_positive(self):
        """Test detect positive emotion."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("ขอบคุณมากๆ ❤️")

        assert result.intent == Intent.EMOTIONAL
        assert result.sub_category == "positive"

    def test_detect_emotional_negative(self):
        """Test detect negative emotion."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("วันนี้เศร้าจัง 😢")

        assert result.intent == Intent.EMOTIONAL
        assert result.sub_category == "negative"

    def test_detect_casual(self):
        """Test detect casual message."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        result = detector.detect("asdfgh")

        assert result.intent == Intent.CASUAL
        assert result.confidence == 0.5


class TestGlobalInstance:
    """Tests for global instance and convenience function."""

    def test_intent_detector_singleton(self):
        """Test global intent_detector exists."""
        from cogs.ai_core.processing.intent_detector import intent_detector

        assert intent_detector is not None

    def test_detect_intent_function(self):
        """Test detect_intent convenience function."""
        from cogs.ai_core.processing.intent_detector import detect_intent

        result = detect_intent("Hello!")

        assert result is not None
        assert result.intent is not None

    def test_detect_intent_returns_intent_result(self):
        """Test detect_intent returns IntentResult."""
        from cogs.ai_core.processing.intent_detector import IntentResult, detect_intent

        result = detect_intent("Test message")

        assert isinstance(result, IntentResult)


class TestIntentPatterns:
    """Tests for intent patterns."""

    def test_patterns_exist(self):
        """Test INTENT_PATTERNS dict exists."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        assert IntentDetector.INTENT_PATTERNS is not None
        assert len(IntentDetector.INTENT_PATTERNS) > 0

    def test_patterns_have_tuples(self):
        """Test patterns are tuples."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        for _intent, patterns in IntentDetector.INTENT_PATTERNS.items():
            for pattern_tuple in patterns:
                assert len(pattern_tuple) == 3
                assert isinstance(pattern_tuple[0], str)  # regex string
                assert isinstance(pattern_tuple[1], str)  # sub_category
                assert isinstance(pattern_tuple[2], float)  # confidence


class TestModuleImports:
    """Tests for module imports."""

    def test_import_classes(self):
        """Test classes can be imported."""
        from cogs.ai_core.processing.intent_detector import (
            Intent,
            IntentDetector,
            IntentResult,
            detect_intent,
            intent_detector,
        )

        assert Intent is not None
        assert IntentResult is not None
        assert IntentDetector is not None
        assert intent_detector is not None
        assert detect_intent is not None
