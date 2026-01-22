"""Tests for localization module."""

import pytest


class TestLanguageEnum:
    """Tests for Language enum."""

    def test_language_thai(self):
        """Test Thai language enum."""
        from utils.localization import Language
        
        assert Language.THAI.value == "th"

    def test_language_english(self):
        """Test English language enum."""
        from utils.localization import Language
        
        assert Language.ENGLISH.value == "en"


class TestDefaultLanguage:
    """Tests for default language."""

    def test_default_language_is_thai(self):
        """Test default language is Thai."""
        from utils.localization import DEFAULT_LANGUAGE, Language
        
        assert DEFAULT_LANGUAGE == Language.THAI


class TestMessages:
    """Tests for MESSAGES dictionary."""

    def test_messages_exists(self):
        """Test MESSAGES dictionary exists."""
        from utils.localization import MESSAGES
        
        assert MESSAGES is not None
        assert isinstance(MESSAGES, dict)

    def test_messages_has_ai_busy(self):
        """Test messages contains ai_busy."""
        from utils.localization import MESSAGES
        
        assert "ai_busy" in MESSAGES
        assert "th" in MESSAGES["ai_busy"]
        assert "en" in MESSAGES["ai_busy"]

    def test_messages_has_ai_error(self):
        """Test messages contains ai_error."""
        from utils.localization import MESSAGES
        
        assert "ai_error" in MESSAGES

    def test_messages_has_voice_not_connected(self):
        """Test messages contains voice_not_connected."""
        from utils.localization import MESSAGES
        
        assert "voice_not_connected" in MESSAGES

    def test_messages_has_music_paused(self):
        """Test messages contains music_paused."""
        from utils.localization import MESSAGES
        
        assert "music_paused" in MESSAGES

    def test_messages_bilingual(self):
        """Test all messages have both Thai and English."""
        from utils.localization import MESSAGES
        
        for key, translations in MESSAGES.items():
            assert "th" in translations, f"{key} missing Thai translation"
            assert "en" in translations, f"{key} missing English translation"


class TestGetMessage:
    """Tests for get_message function."""

    def test_get_message_exists(self):
        """Test get_message function exists."""
        from utils.localization import get_message
        
        assert callable(get_message)

    def test_get_message_thai(self):
        """Test get_message returns Thai message."""
        from utils.localization import get_message, Language
        
        result = get_message("ai_error", Language.THAI)
        
        assert "ผิดพลาด" in result or "error" in result.lower()

    def test_get_message_english(self):
        """Test get_message returns English message."""
        from utils.localization import get_message, Language
        
        result = get_message("ai_error", Language.ENGLISH)
        
        assert "error" in result.lower()

    def test_get_message_default_language(self):
        """Test get_message uses default language."""
        from utils.localization import get_message
        
        result = get_message("ai_error")
        
        assert result is not None
        assert len(result) > 0

    def test_get_message_with_format(self):
        """Test get_message with format parameters."""
        from utils.localization import get_message, Language
        
        result = get_message("voice_joined", Language.ENGLISH, channel="Test")
        
        assert "Test" in result

    def test_get_message_unknown_key(self):
        """Test get_message with unknown key."""
        from utils.localization import get_message
        
        result = get_message("unknown_key_12345")
        
        # Should return something (either empty or key itself)
        assert result is not None


class TestModuleImports:
    """Tests for module imports."""

    def test_import_localization(self):
        """Test localization module can be imported."""
        from utils import localization
        
        assert localization is not None

    def test_import_language(self):
        """Test Language enum can be imported."""
        from utils.localization import Language
        
        assert Language is not None

    def test_import_messages(self):
        """Test MESSAGES can be imported."""
        from utils.localization import MESSAGES
        
        assert MESSAGES is not None

    def test_import_get_message(self):
        """Test get_message can be imported."""
        from utils.localization import get_message
        
        assert get_message is not None


class TestMessageCategories:
    """Tests for message categories."""

    def test_ai_messages_exist(self):
        """Test AI-related messages exist."""
        from utils.localization import MESSAGES
        
        ai_keys = [k for k in MESSAGES.keys() if k.startswith("ai_")]
        assert len(ai_keys) > 0

    def test_voice_messages_exist(self):
        """Test voice-related messages exist."""
        from utils.localization import MESSAGES
        
        voice_keys = [k for k in MESSAGES.keys() if k.startswith("voice_")]
        assert len(voice_keys) > 0

    def test_music_messages_exist(self):
        """Test music-related messages exist."""
        from utils.localization import MESSAGES
        
        music_keys = [k for k in MESSAGES.keys() if k.startswith("music_")]
        assert len(music_keys) > 0


class TestMessageContent:
    """Tests for message content."""

    def test_ai_busy_has_emoji(self):
        """Test ai_busy message has emoji."""
        from utils.localization import MESSAGES
        
        th_msg = MESSAGES["ai_busy"]["th"]
        en_msg = MESSAGES["ai_busy"]["en"]
        
        assert "⏳" in th_msg or "⏳" in en_msg

    def test_ai_context_cleared_has_emoji(self):
        """Test ai_context_cleared has emoji."""
        from utils.localization import MESSAGES
        
        th_msg = MESSAGES["ai_context_cleared"]["th"]
        
        assert "🗑️" in th_msg

    def test_music_paused_has_emoji(self):
        """Test music_paused has emoji."""
        from utils.localization import MESSAGES
        
        th_msg = MESSAGES["music_paused"]["th"]
        
        assert "⏸️" in th_msg
