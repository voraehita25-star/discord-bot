"""
Tests for utils.localization module.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestLocalizationModule:
    """Tests for localization module."""

    def test_module_imports(self):
        """Test module can be imported."""
        from utils import localization

        assert localization is not None


class TestLanguageEnum:
    """Tests for Language enum."""

    def test_thai_language(self):
        """Test Thai language value."""
        from utils.localization import Language

        assert Language.THAI.value == "th"

    def test_english_language(self):
        """Test English language value."""
        from utils.localization import Language

        assert Language.ENGLISH.value == "en"


class TestDefaultLanguage:
    """Tests for default language setting."""

    def test_default_language_is_thai(self):
        """Test default language is Thai."""
        from utils.localization import DEFAULT_LANGUAGE, Language

        assert DEFAULT_LANGUAGE == Language.THAI


class TestMessages:
    """Tests for MESSAGES dictionary."""

    def test_messages_dict_exists(self):
        """Test MESSAGES dictionary exists."""
        from utils.localization import MESSAGES

        assert isinstance(MESSAGES, dict)

    def test_messages_have_both_languages(self):
        """Test messages have both Thai and English."""
        from utils.localization import MESSAGES

        for key, translations in MESSAGES.items():
            assert "th" in translations, f"Missing Thai for {key}"
            assert "en" in translations, f"Missing English for {key}"

    def test_ai_busy_message_exists(self):
        """Test AI busy message exists."""
        from utils.localization import MESSAGES

        assert "ai_busy" in MESSAGES
        assert "⏳" in MESSAGES["ai_busy"]["th"]

    def test_ai_error_message_exists(self):
        """Test AI error message exists."""
        from utils.localization import MESSAGES

        assert "ai_error" in MESSAGES
        assert "❌" in MESSAGES["ai_error"]["th"]

    def test_ai_context_cleared_message(self):
        """Test AI context cleared message."""
        from utils.localization import MESSAGES

        assert "ai_context_cleared" in MESSAGES

    def test_ai_thinking_messages(self):
        """Test AI thinking mode messages."""
        from utils.localization import MESSAGES

        assert "ai_thinking_on" in MESSAGES
        assert "ai_thinking_off" in MESSAGES

    def test_ai_streaming_messages(self):
        """Test AI streaming mode messages."""
        from utils.localization import MESSAGES

        assert "ai_streaming_on" in MESSAGES
        assert "ai_streaming_off" in MESSAGES

    def test_ai_rate_limited_message(self):
        """Test AI rate limited message."""
        from utils.localization import MESSAGES

        assert "ai_rate_limited" in MESSAGES


class TestGetMessage:
    """Tests for get_message function."""

    def test_get_message_thai(self):
        """Test getting Thai message."""
        from utils.localization import Language, get_message

        result = get_message("ai_busy", Language.THAI)
        assert "AI" in result or "ระบบ" in result

    def test_get_message_english(self):
        """Test getting English message."""
        from utils.localization import Language, get_message

        result = get_message("ai_busy", Language.ENGLISH)
        assert "AI" in result

    def test_get_message_default_language(self):
        """Test getting message with default language."""
        from utils.localization import get_message

        result = get_message("ai_busy")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_message_unknown_key(self):
        """Test getting message with unknown key."""
        from utils.localization import get_message

        result = get_message("nonexistent_key_12345")
        # Should return the key itself or empty string
        assert isinstance(result, str)

    def test_get_message_with_formatting(self):
        """Test getting message with formatting."""
        from utils.localization import get_message

        # Some messages may have placeholders
        result = get_message("ai_busy")
        assert isinstance(result, str)


class TestVoiceMusicMessages:
    """Tests for voice/music related messages."""

    def test_voice_not_connected_message(self):
        """Test voice not connected message exists."""
        from utils.localization import MESSAGES

        assert "voice_not_connected" in MESSAGES


class TestFormatMessage:
    """Tests for message formatting via get_message."""

    def test_format_message_with_kwargs(self):
        """Test formatting message with kwargs."""
        from utils.localization import Language, get_message

        # voice_joined has {channel} placeholder
        result = get_message("voice_joined", Language.THAI, channel="General")
        assert "General" in result

    def test_format_message_returns_string(self):
        """Test get_message returns string."""
        from utils.localization import get_message

        result = get_message("ai_error")
        assert isinstance(result, str)

    def test_msg_shorthand_function(self):
        """Test msg shorthand function."""
        from utils.localization import msg

        result = msg("ai_busy")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_msg_en_shorthand_function(self):
        """Test msg_en shorthand function."""
        from utils.localization import msg_en

        result = msg_en("ai_busy")
        assert isinstance(result, str)
        assert "AI" in result  # English should have "AI"


class TestLocalizedMessagesClass:
    """Tests for LocalizedMessages class."""

    def test_init_with_thai(self):
        """Test initialization with Thai."""
        from utils.localization import Language, LocalizedMessages

        lm = LocalizedMessages(Language.THAI)
        assert lm.lang == Language.THAI

    def test_init_with_english(self):
        """Test initialization with English."""
        from utils.localization import Language, LocalizedMessages

        lm = LocalizedMessages(Language.ENGLISH)
        assert lm.lang == Language.ENGLISH

    def test_get_method(self):
        """Test get method."""
        from utils.localization import Language, LocalizedMessages

        lm = LocalizedMessages(Language.ENGLISH)
        result = lm.get("ai_busy")
        assert "AI" in result

    def test_attribute_access(self):
        """Test attribute-style access."""
        from utils.localization import Language, LocalizedMessages

        lm = LocalizedMessages(Language.ENGLISH)
        result = lm.ai_busy
        assert isinstance(result, str)

    def test_pre_initialized_thai_messages(self):
        """Test pre-initialized thai_messages."""
        from utils.localization import thai_messages

        assert thai_messages is not None
        result = thai_messages.ai_busy
        assert isinstance(result, str)

    def test_pre_initialized_english_messages(self):
        """Test pre-initialized english_messages."""
        from utils.localization import english_messages

        result = english_messages.ai_busy
        assert "AI" in result


class TestAllMessages:
    """Tests to verify all messages are valid."""

    def test_all_messages_are_strings(self):
        """Test all message values are strings."""
        from utils.localization import MESSAGES

        for key, translations in MESSAGES.items():
            for lang, message in translations.items():
                assert isinstance(message, str), f"Message {key}.{lang} is not a string"

    def test_all_messages_non_empty(self):
        """Test all messages are non-empty."""
        from utils.localization import MESSAGES

        for key, translations in MESSAGES.items():
            for lang, message in translations.items():
                assert len(message) > 0, f"Message {key}.{lang} is empty"
