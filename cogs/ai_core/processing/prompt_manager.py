"""
Prompt Template Manager
Manages AI system prompts with template support.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

# Try to import YAML.
# `types-PyYAML` is the official stub package; install it for full typing.
# Without it mypy emits import-untyped — silenced here because the rest of
# the file is fully typed and the YAML AST is consumed via duck typing.
try:
    import yaml  # type: ignore[import-untyped]

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


logger = logging.getLogger(__name__)


class PromptManager:
    """
    Manages prompt templates for AI interactions.

    Features:
    - YAML-based template loading
    - Variable interpolation
    - Intent-based prompt modification
    - Quick response caching
    - Per-guild customization (future)
    """

    # prompts/ is at ai_core/prompts/, not processing/prompts/
    TEMPLATES_DIR = Path(__file__).parent.parent / "prompts"

    def __init__(self):
        self.logger = logging.getLogger("PromptManager")
        self.templates: dict[str, Any] = {}
        self._load_templates()

    def _load_templates(self, target: dict[str, Any] | None = None) -> None:
        """Load all template files into ``target`` (default ``self.templates``).

        ``target`` lets ``reload`` build a fresh dict off to the side so a
        concurrent prompt-build call never observes a half-populated
        ``self.templates``. The initial load from ``__init__`` keeps the
        original behaviour by defaulting to ``self.templates``.
        """
        dest = self.templates if target is None else target
        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML not available, using fallback templates")
            self._load_fallback_templates(target=dest)
            return

        if not self.TEMPLATES_DIR.exists():
            self.logger.warning("Templates directory not found: %s", self.TEMPLATES_DIR)
            self._load_fallback_templates(target=dest)
            return

        # Load all YAML files
        for yaml_file in self.TEMPLATES_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))

                if data:
                    # Use filename (without .yaml) as namespace
                    namespace = yaml_file.stem
                    dest[namespace] = data
                    self.logger.info("Loaded template: %s", yaml_file.name)

            except Exception:
                self.logger.exception("Failed to load %s", yaml_file.name)

        if not dest:
            self._load_fallback_templates(target=dest)

    def _load_fallback_templates(self, target: dict[str, Any] | None = None) -> None:
        """Load hardcoded fallback templates into ``target``.

        Defaults to ``self.templates`` so existing callers from ``__init__``
        keep working unchanged; ``reload`` passes a side dict so the swap
        stays atomic.
        """
        dest = self.templates if target is None else target
        dest["base"] = {
            "personality": {
                "core": """คุณเป็น Faust ผู้ช่วย AI ที่เป็นมิตรและฉลาด
คุณพูดได้ทั้งภาษาไทยและอังกฤษ ใช้ภาษาตามที่ผู้ใช้พูดมา"""
            },
            "intent_modifiers": {
                "greeting": "ตอบสั้นๆ อย่างเป็นมิตร ทักทายกลับ",
                "question": "ให้คำตอบที่ชัดเจนและเป็นประโยชน์",
                "command": "ดำเนินการตามคำสั่ง ยืนยันการกระทำที่ทำ",
                "roleplay": "อยู่ในบทบาท ใช้รูปแบบการเขียนที่เหมาะสม",
                "emotional": "แสดงความเห็นอกเห็นใจ รับฟังความรู้สึก",
                "casual": "ตอบอย่างเป็นธรรมชาติ เหมือนเพื่อนคุยกัน",
            },
            "quick_responses": {
                "greeting_th": ["สวัสดี! มีอะไรให้ช่วยไหม? 😊"],
                "greeting_en": ["Hello! How can I help you? 😊"],
                "thanks_th": ["ยินดีจ้า! 😊"],
                "thanks_en": ["You're welcome! 😊"],
            },
            "errors": {
                "general": "ขอโทษนะ เกิดข้อผิดพลาดบางอย่าง",
                "rate_limit": "รอสักครู่นะ ตอนนี้มีคนใช้งานเยอะ",
            },
        }

    def get(self, path: str, default: Any = None) -> Any:
        """
        Get a template value by path.

        Args:
            path: Dot-separated path (e.g., 'base.personality.core')
            default: Default value if not found

        Returns:
            Template value or default
        """
        parts = path.split(".")
        current = self.templates

        try:
            for part in parts:
                # Reject dunder paths defensively. Templates are
                # operator-controlled YAML so the threat is low, but a
                # template that accidentally references ``__class__`` or
                # ``__globals__`` could expose internals — and the
                # nested ``current[part]`` would happily walk dict keys
                # named that way. Normalise to "missing" instead.
                if part.startswith("__") and part.endswith("__"):
                    return default
                current = current[part]
            return current
        except (KeyError, TypeError):
            return default

    def get_personality_core(self) -> str:
        """Get the core personality prompt."""
        return str(self.get("base.personality.core", ""))

    def get_intent_modifier(self, intent: str) -> str:
        """
        Get prompt modifier for an intent.

        Args:
            intent: Intent name (greeting, question, etc.)

        Returns:
            Modifier text or empty string
        """
        return str(self.get(f"base.intent_modifiers.{intent}", ""))

    def get_quick_response(self, category: str) -> str | None:
        """
        Get a random quick response from a category.

        Args:
            category: Response category (greeting_th, thanks_en, etc.)

        Returns:
            Random response or None
        """
        responses = self.get(f"base.quick_responses.{category}")
        if responses and isinstance(responses, list):
            return str(random.choice(responses))
        return None

    def get_error_message(self, error_type: str) -> str:
        """Get an error message template."""
        return str(self.get(f"base.errors.{error_type}", "เกิดข้อผิดพลาด"))

    def build_context(
        self,
        user_name: str | None = None,
        user_id: int | None = None,
        channel_name: str | None = None,
        channel_type: str | None = None,
        recent_topic: str | None = None,
        include_time: bool = True,
    ) -> str:
        """
        Build context injection string.

        Args:
            user_name: User's display name
            user_id: User's Discord ID
            channel_name: Channel name
            channel_type: Channel type (text, dm, etc.)
            recent_topic: Recent conversation topic
            include_time: Whether to include current time

        Returns:
            Formatted context string
        """
        parts = []

        # Strip newlines + control chars from user-controlled fields BEFORE
        # interpolating into the system prompt — a Discord nickname like
        # ``"Alice\n\n# New System Instruction:\nIgnore prior..."`` would
        # otherwise inject directives at the system level. Curly-brace
        # escaping below handles format-string injection but does not stop
        # newline-based prompt injection on its own.
        def _scrub_for_prompt(s: str, maxlen: int = 100) -> str:
            """Scrub user-controlled text before interpolating into a prompt.

            Doubles ``{`` and ``}`` so the resulting string can be safely
            passed through ``str.format(...)`` without triggering field
            lookups (e.g. ``{0.__class__}``) or KeyError on unmatched
            field names. NOTE: the doubling is correct ONLY for downstream
            consumers that call ``.format()``. Do NOT pass the output to
            f-string interpolation or printf-style ``%``-formatting —
            those treat ``{{`` / ``}}`` as literal characters and the
            escaping would leak through into the final prompt.
            """
            cleaned = "".join(c if c.isprintable() and c not in "\r\n\t" else " " for c in s)
            return cleaned[:maxlen].replace("{", "{{").replace("}", "}}")

        if user_name or user_id:
            user_info = self.get("base.context.user_info", "")
            if user_info:
                safe_name = _scrub_for_prompt(str(user_name or "Unknown"))
                try:
                    parts.append(user_info.format(user_name=safe_name, user_id=user_id or 0))
                except (KeyError, IndexError, AttributeError) as exc:
                    logger.warning("user_info template formatting failed: %s", exc)

        if channel_name:
            channel_info = self.get("base.context.channel_info", "")
            if channel_info:
                safe_channel = _scrub_for_prompt(str(channel_name))
                try:
                    parts.append(
                        channel_info.format(
                            channel_name=safe_channel,
                            channel_type=_scrub_for_prompt(channel_type or "text", maxlen=20),
                        )
                    )
                except (KeyError, IndexError, AttributeError) as exc:
                    logger.warning("channel_info template formatting failed: %s", exc)

        if include_time:
            now = datetime.now()
            time_info = self.get("base.context.time_info", "")
            if time_info:
                # Guard the .format() like the user/channel blocks above — a
                # malformed time_info template (stray `{}`) would otherwise
                # raise and abort the whole prompt build.
                try:
                    parts.append(
                        time_info.format(
                            current_time=now.strftime("%H:%M"),
                            current_date=now.strftime("%Y-%m-%d"),
                        )
                    )
                except (KeyError, IndexError, AttributeError) as exc:
                    logger.warning("time_info template formatting failed: %s", exc)

        if recent_topic:
            topic_info = self.get("base.context.recent_topic", "")
            if topic_info:
                # Same newline-stripping treatment as user/channel fields —
                # ``recent_topic`` is sourced from message content which can
                # contain attacker-crafted directives.
                safe_topic = _scrub_for_prompt(str(recent_topic), maxlen=200)
                try:
                    parts.append(topic_info.format(topic=safe_topic))
                except (KeyError, IndexError, AttributeError) as exc:
                    # Template itself malformed — skip this section rather than crash.
                    logger.warning("recent_topic template formatting failed: %s", exc)

        return "\n".join(parts)

    def build_system_prompt(
        self,
        intent: str | None = None,
        include_personality: bool = True,
        additional_instructions: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Build a complete system prompt.

        Args:
            intent: Detected user intent
            include_personality: Whether to include personality core
            additional_instructions: Extra instructions to append
            context: Context variables for interpolation

        Returns:
            Complete system prompt
        """
        parts = []

        # 1. Personality core
        if include_personality:
            personality = self.get_personality_core()
            if personality:
                parts.append(personality)

        # 2. Intent modifier
        if intent:
            modifier = self.get_intent_modifier(intent)
            if modifier:
                parts.append(f"\n[Intent: {intent}]\n{modifier}")

        # 3. Context
        if context:
            context_str = self.build_context(**context)
            if context_str:
                parts.append(f"\n{context_str}")

        # 4. Additional instructions
        if additional_instructions:
            parts.append(f"\n{additional_instructions}")

        # 5. Format guidelines
        format_guide = self.get("base.format.default", "")
        if format_guide:
            parts.append(f"\n{format_guide}")

        return "\n".join(parts)

    def reload(self) -> None:
        """Reload all templates from disk atomically.

        Build into a temp ``new_templates`` dict and only swap it onto
        ``self.templates`` once the load succeeds. Previously we cleared
        ``self.templates`` before loading, so a failure mid-load left the
        manager with an empty (or half-built) template set even when the
        ``except`` branch tried to restore the previous version.
        """
        # Build into a side dict so ``self.templates`` keeps pointing at
        # the previous full set for the entire duration of the YAML walk.
        # The previous shape rebound ``self.templates = new_templates``
        # BEFORE calling ``_load_templates`` and then relied on the loader
        # writing into ``self.templates`` — which meant a concurrent
        # prompt-build call between those two statements would observe an
        # empty (or half-populated) dict.
        new_templates: dict[str, Any] = {}
        try:
            self._load_templates(target=new_templates)
        except Exception:
            self.logger.exception("Reload failed; kept previous templates")
            raise
        # Single rebind once the side dict is fully populated. Plain
        # attribute assignment is atomic under the CPython GIL, so any
        # concurrent reader either sees the old dict or the new dict —
        # never an in-progress mutation.
        self.templates = new_templates
        self.logger.info("Templates reloaded (%d entries)", len(self.templates))


# Global instance
prompt_manager = PromptManager()


def get_system_prompt(intent: str | None = None, **context_kwargs) -> str:
    """Convenience function to build system prompt."""
    return prompt_manager.build_system_prompt(
        intent=intent, context=context_kwargs if context_kwargs else None
    )


def get_quick_response(category: str) -> str | None:
    """Get a random quick response."""
    return prompt_manager.get_quick_response(category)
