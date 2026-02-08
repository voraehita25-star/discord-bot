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


class TestIntentDetectorHelpers:
    """Tests for helper methods."""

    def test_is_simple_greeting_true(self):
        """Test is_simple_greeting returns True."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector.is_simple_greeting("สวัสดี")

        assert result is True

    def test_is_simple_greeting_false_long(self):
        """Test is_simple_greeting returns False for long non-greeting message."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        # Use a longer complex message that doesn't start with greeting
        result = detector.is_simple_greeting(
            "นี่คือคำถามที่ยาวมากเกี่ยวกับหัวข้อที่ซับซ้อนซึ่งต้องการคำตอบที่ละเอียด"
        )

        assert result is False

    def test_is_simple_greeting_false_not_greeting(self):
        """Test is_simple_greeting returns False for non-greeting."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector.is_simple_greeting("นี่คืออะไร?")

        assert result is False

    def test_requires_context_roleplay(self):
        """Test requires_context for roleplay."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector.requires_context("{{Character}} continues the story")

        assert result is True

    def test_requires_context_question(self):
        """Test requires_context for question."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector.requires_context("What does this mean?")

        assert result is True

    def test_requires_context_pronoun_reference(self):
        """Test requires_context with pronoun reference."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector.requires_context("Tell me more about it")

        assert result is True

    def test_requires_context_false(self):
        """Test requires_context returns False for standalone message."""
        from cogs.ai_core.processing.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector.requires_context("Hello")

        assert result is False


class TestGetPromptModifier:
    """Tests for get_prompt_modifier method."""

    def test_modifier_greeting(self):
        """Test modifier for GREETING."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        modifier = detector.get_prompt_modifier(Intent.GREETING)

        assert "friendly" in modifier.lower()

    def test_modifier_question(self):
        """Test modifier for QUESTION."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        modifier = detector.get_prompt_modifier(Intent.QUESTION)

        assert "answer" in modifier.lower() or "informative" in modifier.lower()

    def test_modifier_command(self):
        """Test modifier for COMMAND."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        modifier = detector.get_prompt_modifier(Intent.COMMAND)

        assert "action" in modifier.lower() or "execute" in modifier.lower()

    def test_modifier_roleplay(self):
        """Test modifier for ROLEPLAY."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        modifier = detector.get_prompt_modifier(Intent.ROLEPLAY)

        assert "character" in modifier.lower()

    def test_modifier_emotional(self):
        """Test modifier for EMOTIONAL."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        modifier = detector.get_prompt_modifier(Intent.EMOTIONAL)

        assert "empathetic" in modifier.lower() or "supportive" in modifier.lower()

    def test_modifier_unknown(self):
        """Test modifier for UNKNOWN is empty."""
        from cogs.ai_core.processing.intent_detector import Intent, IntentDetector

        detector = IntentDetector()
        modifier = detector.get_prompt_modifier(Intent.UNKNOWN)

        assert modifier == ""


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

        for intent, patterns in IntentDetector.INTENT_PATTERNS.items():
            for pattern_tuple in patterns:
                assert len(pattern_tuple) == 3
                assert isinstance(pattern_tuple[0], str)  # regex string
                assert isinstance(pattern_tuple[1], str)  # sub_category
                assert isinstance(pattern_tuple[2], float)  # confidence


class TestModuleImports:
    """Tests for module imports."""

    def test_module_imports(self):
        """Test module can be imported."""
        import cogs.ai_core.processing.intent_detector

        assert cogs.ai_core.processing.intent_detector is not None

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
