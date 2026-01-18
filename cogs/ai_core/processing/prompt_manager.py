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

# Try to import YAML
try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


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

    def _load_templates(self) -> None:
        """Load all template files from prompts directory."""
        if not YAML_AVAILABLE:
            self.logger.warning("PyYAML not available, using fallback templates")
            self._load_fallback_templates()
            return

        if not self.TEMPLATES_DIR.exists():
            self.logger.warning("Templates directory not found: %s", self.TEMPLATES_DIR)
            self._load_fallback_templates()
            return

        # Load all YAML files
        for yaml_file in self.TEMPLATES_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))

                if data:
                    # Use filename (without .yaml) as namespace
                    namespace = yaml_file.stem
                    self.templates[namespace] = data
                    self.logger.info("Loaded template: %s", yaml_file.name)

            except Exception as e:
                self.logger.error("Failed to load %s: %s", yaml_file.name, e)

        if not self.templates:
            self._load_fallback_templates()

    def _load_fallback_templates(self) -> None:
        """Load hardcoded fallback templates."""
        self.templates["base"] = {
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
                current = current[part]
            return current
        except (KeyError, TypeError):
            return default

    def get_personality_core(self) -> str:
        """Get the core personality prompt."""
        return self.get("base.personality.core", "")

    def get_intent_modifier(self, intent: str) -> str:
        """
        Get prompt modifier for an intent.

        Args:
            intent: Intent name (greeting, question, etc.)

        Returns:
            Modifier text or empty string
        """
        return self.get(f"base.intent_modifiers.{intent}", "")

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
            return random.choice(responses)
        return None

    def get_error_message(self, error_type: str) -> str:
        """Get an error message template."""
        return self.get(f"base.errors.{error_type}", "เกิดข้อผิดพลาด")

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

        if user_name or user_id:
            user_info = self.get("base.context.user_info", "")
            if user_info:
                parts.append(
                    user_info.format(user_name=user_name or "Unknown", user_id=user_id or 0)
                )

        if channel_name:
            channel_info = self.get("base.context.channel_info", "")
            if channel_info:
                parts.append(
                    channel_info.format(
                        channel_name=channel_name, channel_type=channel_type or "text"
                    )
                )

        if include_time:
            now = datetime.now()
            time_info = self.get("base.context.time_info", "")
            if time_info:
                parts.append(
                    time_info.format(
                        current_time=now.strftime("%H:%M"), current_date=now.strftime("%Y-%m-%d")
                    )
                )

        if recent_topic:
            topic_info = self.get("base.context.recent_topic", "")
            if topic_info:
                parts.append(topic_info.format(topic=recent_topic))

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
        """Reload all templates from disk."""
        self.templates.clear()
        self._load_templates()
        self.logger.info("Templates reloaded")


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
