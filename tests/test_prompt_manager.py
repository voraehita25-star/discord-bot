"""
Tests for cogs/ai_core/processing/prompt_manager.py

Comprehensive tests for PromptManager and related functions.
"""




class TestPromptManagerInit:
    """Tests for PromptManager initialization."""

    def test_init_creates_logger(self):
        """Test logger is created."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        assert manager.logger is not None

    def test_init_loads_templates(self):
        """Test templates are loaded."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        assert manager.templates is not None

    def test_init_has_fallback_templates(self):
        """Test fallback templates are available."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        # Should have at least base templates
        assert "base" in manager.templates or len(manager.templates) > 0


class TestPromptManagerLoadFallback:
    """Tests for _load_fallback_templates method."""

    def test_fallback_has_personality(self):
        """Test fallback has personality."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        assert "base" in manager.templates
        assert "personality" in manager.templates["base"]

    def test_fallback_has_intent_modifiers(self):
        """Test fallback has intent modifiers."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        assert "intent_modifiers" in manager.templates["base"]

    def test_fallback_has_quick_responses(self):
        """Test fallback has quick responses."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        assert "quick_responses" in manager.templates["base"]

    def test_fallback_has_errors(self):
        """Test fallback has error messages."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        assert "errors" in manager.templates["base"]


class TestPromptManagerGet:
    """Tests for get method."""

    def test_get_existing_path(self):
        """Test get with existing path."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get("base.personality.core")
        assert result is not None
        assert isinstance(result, str)

    def test_get_nested_path(self):
        """Test get with nested path."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get("base.intent_modifiers.greeting")
        assert result is not None

    def test_get_nonexistent_path(self):
        """Test get with nonexistent path."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get("nonexistent.path", "default")
        assert result == "default"

    def test_get_returns_default(self):
        """Test get returns default when not found."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()

        result = manager.get("does.not.exist", "my_default")
        assert result == "my_default"


class TestGetPersonalityCore:
    """Tests for get_personality_core method."""

    def test_get_personality_core(self):
        """Test get_personality_core returns string."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_personality_core()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_personality_core_contains_faust(self):
        """Test personality mentions Faust."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_personality_core()
        assert "Faust" in result


class TestGetIntentModifier:
    """Tests for get_intent_modifier method."""

    def test_get_greeting_modifier(self):
        """Test get greeting modifier."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_intent_modifier("greeting")
        assert isinstance(result, str)

    def test_get_question_modifier(self):
        """Test get question modifier."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_intent_modifier("question")
        assert isinstance(result, str)

    def test_get_unknown_modifier(self):
        """Test get unknown modifier returns empty."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_intent_modifier("unknown_intent")
        assert result == ""


class TestGetQuickResponse:
    """Tests for get_quick_response method."""

    def test_get_quick_response_greeting_th(self):
        """Test get Thai greeting response."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_quick_response("greeting_th")
        assert result is not None
        assert isinstance(result, str)

    def test_get_quick_response_greeting_en(self):
        """Test get English greeting response."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_quick_response("greeting_en")
        assert result is not None
        assert isinstance(result, str)

    def test_get_quick_response_nonexistent(self):
        """Test get nonexistent category returns None."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_quick_response("nonexistent")
        assert result is None


class TestGetErrorMessage:
    """Tests for get_error_message method."""

    def test_get_general_error(self):
        """Test get general error message."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_error_message("general")
        assert result is not None
        assert isinstance(result, str)

    def test_get_rate_limit_error(self):
        """Test get rate limit error message."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_error_message("rate_limit")
        assert result is not None

    def test_get_unknown_error(self):
        """Test get unknown error returns default."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.get_error_message("unknown_error")
        assert "ผิดพลาด" in result


class TestBuildContext:
    """Tests for build_context method."""

    def test_build_context_empty(self):
        """Test build context with no params."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_context()
        # May return empty or just time
        assert isinstance(result, str)

    def test_build_context_with_user(self):
        """Test build context with user info."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_context(user_name="TestUser", user_id=12345)
        assert isinstance(result, str)

    def test_build_context_without_time(self):
        """Test build context without time."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_context(include_time=False)
        assert isinstance(result, str)


class TestBuildSystemPrompt:
    """Tests for build_system_prompt method."""

    def test_build_system_prompt_default(self):
        """Test build default system prompt."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_system_prompt_with_intent(self):
        """Test build system prompt with intent."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_system_prompt(intent="greeting")
        assert isinstance(result, str)

    def test_build_system_prompt_with_additional(self):
        """Test build system prompt with additional instructions."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_system_prompt(additional_instructions="Be extra helpful")
        assert "extra helpful" in result

    def test_build_system_prompt_without_personality(self):
        """Test build system prompt without personality."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_system_prompt(include_personality=False)
        assert isinstance(result, str)

    def test_build_system_prompt_with_context(self):
        """Test build system prompt with context."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()
        manager._load_fallback_templates()

        result = manager.build_system_prompt(
            context={"user_name": "TestUser", "channel_name": "general"}
        )
        assert isinstance(result, str)


class TestReload:
    """Tests for reload method."""

    def test_reload_clears_templates(self):
        """Test reload clears and reloads templates."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        manager = PromptManager()

        # Add extra key
        manager.templates["test_key"] = "test_value"

        manager.reload()

        # Should be reloaded (test_key gone if fallback used)
        # Just check templates is not empty
        assert manager.templates is not None


class TestGlobalInstance:
    """Tests for global instance and functions."""

    def test_prompt_manager_singleton(self):
        """Test global prompt_manager exists."""
        from cogs.ai_core.processing.prompt_manager import prompt_manager

        assert prompt_manager is not None

    def test_get_system_prompt_function(self):
        """Test get_system_prompt convenience function."""
        from cogs.ai_core.processing.prompt_manager import get_system_prompt

        result = get_system_prompt()
        assert isinstance(result, str)

    def test_get_system_prompt_with_intent(self):
        """Test get_system_prompt with intent."""
        from cogs.ai_core.processing.prompt_manager import get_system_prompt

        result = get_system_prompt(intent="question")
        assert isinstance(result, str)

    def test_get_quick_response_function(self):
        """Test get_quick_response convenience function."""
        from cogs.ai_core.processing.prompt_manager import get_quick_response

        # May return None if category not found
        result = get_quick_response("greeting_th")
        # Just check it doesn't crash
        assert result is None or isinstance(result, str)


class TestYAMLAvailability:
    """Tests for YAML availability flag."""

    def test_yaml_flag_exists(self):
        """Test YAML_AVAILABLE flag exists."""
        from cogs.ai_core.processing.prompt_manager import YAML_AVAILABLE

        assert isinstance(YAML_AVAILABLE, bool)


class TestTemplatesDir:
    """Tests for templates directory constant."""

    def test_templates_dir_is_path(self):
        """Test TEMPLATES_DIR is Path."""
        from pathlib import Path

        from cogs.ai_core.processing.prompt_manager import PromptManager

        assert isinstance(PromptManager.TEMPLATES_DIR, Path)

    def test_templates_dir_contains_prompts(self):
        """Test path contains 'prompts'."""
        from cogs.ai_core.processing.prompt_manager import PromptManager

        assert "prompts" in str(PromptManager.TEMPLATES_DIR)


class TestModuleImports:
    """Tests for module imports."""

    def test_module_imports(self):
        """Test module can be imported."""
        import cogs.ai_core.processing.prompt_manager

        assert cogs.ai_core.processing.prompt_manager is not None

    def test_import_classes_and_functions(self):
        """Test classes and functions can be imported."""
        from cogs.ai_core.processing.prompt_manager import (
            PromptManager,
            get_quick_response,
            get_system_prompt,
            prompt_manager,
        )

        assert PromptManager is not None
        assert prompt_manager is not None
        assert get_system_prompt is not None
        assert get_quick_response is not None
