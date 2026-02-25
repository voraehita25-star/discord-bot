"""
Intent Detection Module for AI Chat
Classifies user messages by intent for optimized processing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum


class Intent(Enum):
    """User message intent categories."""

    GREETING = "greeting"
    QUESTION = "question"
    COMMAND = "command"
    ROLEPLAY = "roleplay"
    EMOTIONAL = "emotional"
    CASUAL = "casual"
    UNKNOWN = "unknown"


@dataclass
class IntentResult:
    """Result of intent detection."""

    intent: Intent
    confidence: float  # 0.0 to 1.0
    sub_category: str | None = None
    detected_patterns: list[str] | None = None

    def __post_init__(self):
        if self.detected_patterns is None:
            self.detected_patterns = []


class IntentDetector:
    """
    Detects user intent from message content.
    Supports Thai and English patterns.

    Used to:
    - Optimize system prompts based on intent
    - Skip unnecessary processing for simple intents
    - Route messages to appropriate handlers
    """

    # Pattern definitions: (patterns, sub_category, confidence_boost)
    INTENT_PATTERNS = {
        Intent.GREETING: [
            # Thai greetings
            (r"^(?:สวัสดี|หวัดดี|ดีครับ|ดีค่ะ|ดีจ้า|ไง|ว่าไง)", "thai_greeting", 0.9),
            # English greetings
            (
                r"^(?:hi|hello|hey|yo|sup|good\s*(?:morning|afternoon|evening))",
                "english_greeting",
                0.9,
            ),
            # Wake words
            (r"^(?:บอท|bot|น้อง)", "wake_word", 0.7),
        ],
        Intent.QUESTION: [
            # Thai question words
            (
                r"(?:อะไร|ทำไม|อย่างไร|ยังไง|เมื่อไหร่|ที่ไหน|ใคร|กี่|เท่าไหร่|หรือเปล่า|ไหม|มั้ย|รึเปล่า)\s*[?？]*$",
                "thai_question",
                0.85,
            ),
            # English question words
            (
                r"^(?:what|why|how|when|where|who|which|can|could|would|should|is|are|do|does|did)",
                "english_question",
                0.85,
            ),
            # Question marks
            (r"[?？]\s*$", "question_mark", 0.6),
            # Asking patterns
            (r"(?:ช่วย|อยาก(?:รู้|ถาม)|ถาม(?:หน่อย)?|สงสัย)", "thai_asking", 0.8),
        ],
        Intent.COMMAND: [
            # Server management commands
            (
                r"(?:สร้าง|ลบ|แก้ไข|เปลี่ยน|ย้าย|เพิ่ม|ตั้ง|ปิด|เปิด)\s*(?:ห้อง|ช่อง|โรล|role|channel)",
                "server_management",
                0.95,
            ),
            (
                r"(?:create|delete|remove|add|set|change|move|edit)\s*(?:channel|role|category)",
                "server_management_en",
                0.95,
            ),
            # Memory commands
            (r"(?:จำ|จดจำ|บันทึก|remember|memorize|save)", "memory_command", 0.85),
            # Action verbs (imperative)
            (r"^(?:ทำ|หา|บอก|แสดง|ดู|เช็ค|check|show|find|tell|get|list)", "action_verb", 0.7),
        ],
        Intent.ROLEPLAY: [
            # Character tags
            (r"\{\{[^}]+\}\}", "character_tag", 0.95),
            # Action markers
            (r"^[>\*]", "action_marker", 0.9),
            # Roleplay keywords
            (r"(?:roleplay|rp|เล่น(?:บท|เป็น)|สมมติ)", "rp_keyword", 0.85),
            # Story continuation
            (r"(?:ต่อ(?:จาก)?|continue|และแล้ว|จากนั้น)", "story_continue", 0.7),
        ],
        Intent.EMOTIONAL: [
            # Positive emotions
            (r"(?:รัก|ชอบ|ดีใจ|มีความสุข|ขอบคุณ|love|like|happy|thank|❤️|🥰|😊)", "positive", 0.8),
            # Negative emotions
            (r"(?:เศร้า|เหงา|เบื่อ|เหนื่อย|ท้อ|sad|tired|bored|lonely|😢|😔|😞)", "negative", 0.8),
            # Frustration
            (r"(?:โกรธ|หงุดหงิด|รำคาญ|angry|frustrated|annoyed|😠|😤)", "frustrated", 0.8),
        ],
    }

    def __init__(self):
        self.logger = logging.getLogger("IntentDetector")
        # Pre-compile all patterns
        self._compiled_patterns = {}
        for intent, patterns in self.INTENT_PATTERNS.items():
            self._compiled_patterns[intent] = [
                (re.compile(pattern, re.IGNORECASE | re.MULTILINE), sub_cat, conf)
                for pattern, sub_cat, conf in patterns
            ]
        self._pronoun_pattern = re.compile(
            r"\b(?:มัน|นั่น|นี่|เขา|เธอ|พวกเขา|it|that|this|they|them|he|she)\b", re.IGNORECASE
        )

    def detect(self, message: str) -> IntentResult:
        """
        Detect the primary intent of a message.

        Args:
            message: User message text

        Returns:
            IntentResult with detected intent and confidence
        """
        if not message or not message.strip():
            return IntentResult(Intent.UNKNOWN, 0.0)

        message = message.strip()

        # Score each intent
        intent_scores: dict[Intent, tuple[float, str, list[str]]] = {}

        for intent, compiled_patterns in self._compiled_patterns.items():
            max_score = 0.0
            best_sub_cat = None
            detected = []

            for pattern, sub_cat, base_conf in compiled_patterns:
                match = pattern.search(message)
                if match:
                    # Boost confidence for matches at start of message
                    position_boost = 0.1 if match.start() < 5 else 0.0
                    score = base_conf + position_boost

                    detected.append(sub_cat)

                    if score > max_score:
                        max_score = score
                        best_sub_cat = sub_cat

            if max_score > 0:
                intent_scores[intent] = (max_score, best_sub_cat, detected)

        # Find highest scoring intent
        if not intent_scores:
            return IntentResult(Intent.CASUAL, 0.5)

        best_intent = max(intent_scores, key=lambda x: intent_scores[x][0])
        score, sub_cat, detected = intent_scores[best_intent]

        self.logger.debug("Intent detected: %s (%.2f) - %s", best_intent.value, score, sub_cat)

        return IntentResult(
            intent=best_intent,
            confidence=min(score, 1.0),
            sub_category=sub_cat,
            detected_patterns=detected,
        )

    def is_simple_greeting(self, message: str) -> bool:
        """
        Quick check if message is just a simple greeting.
        Can be used to provide cached responses.
        """
        result = self.detect(message)
        return (
            result.intent == Intent.GREETING
            and result.confidence >= 0.8
            and len(message.split()) <= 5
        )

    def requires_context(self, message: str) -> bool:
        """
        Check if message likely requires conversation context.
        """
        result = self.detect(message)

        # These intents typically need context
        context_intents = {Intent.ROLEPLAY, Intent.QUESTION, Intent.EMOTIONAL}

        if result.intent in context_intents:
            return True

        # Check for pronouns that reference previous context
        return bool(self._pronoun_pattern.search(message))

    def get_prompt_modifier(self, intent: Intent) -> str:
        """
        Get a prompt modifier based on detected intent.
        Used to optimize system instructions.
        """
        modifiers = {
            Intent.GREETING: "Respond warmly and briefly. Be friendly.",
            Intent.QUESTION: "Provide a clear, helpful answer. Be informative.",
            Intent.COMMAND: "Execute the requested action. Be precise and confirm actions.",
            Intent.ROLEPLAY: "Stay in character. Use appropriate formatting.",
            Intent.EMOTIONAL: "Be empathetic and supportive. Acknowledge feelings.",
            Intent.CASUAL: "Be conversational and natural.",
            Intent.UNKNOWN: "",
        }
        return modifiers.get(intent, "")


# Global instance
intent_detector = IntentDetector()


def detect_intent(message: str) -> IntentResult:
    """Convenience function to detect intent."""
    return intent_detector.detect(message)
