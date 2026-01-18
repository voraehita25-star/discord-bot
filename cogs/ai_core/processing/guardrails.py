"""
AI Output Guardrails Module
Provides safety validation for AI-generated responses.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

# ==================== UNRESTRICTED MODE ====================
# Channels in this set bypass ALL guardrail checks
# Managed by Owner via !unrestricted command
# Now with PERSISTENT STORAGE - survives bot restarts!

_UNRESTRICTED_FILE = Path(__file__).parent.parent / "data" / "unrestricted_channels.json"
unrestricted_channels: set[int] = set()


def _load_unrestricted_channels() -> set[int]:
    """Load unrestricted channels from persistent storage."""
    try:
        if _UNRESTRICTED_FILE.exists():
            data = json.loads(_UNRESTRICTED_FILE.read_text(encoding="utf-8"))
            channels = set(data.get("channels", []))
            logging.info("🔓 Loaded %d unrestricted channels from storage", len(channels))
            return channels
    except Exception as e:
        logging.warning("Failed to load unrestricted channels: %s", e)
    return set()


def _save_unrestricted_channels() -> bool:
    """Save unrestricted channels to persistent storage."""
    try:
        _UNRESTRICTED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _UNRESTRICTED_FILE.write_text(
            json.dumps({"channels": list(unrestricted_channels)}, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception as e:
        logging.error("Failed to save unrestricted channels: %s", e)
        return False


# Load on module import
unrestricted_channels = _load_unrestricted_channels()


def is_unrestricted(channel_id: int) -> bool:
    """Check if a channel is in unrestricted mode."""
    return channel_id in unrestricted_channels


def set_unrestricted(channel_id: int, enabled: bool) -> bool:
    """Enable or disable unrestricted mode for a channel. Persists to disk."""
    if enabled:
        unrestricted_channels.add(channel_id)
    else:
        unrestricted_channels.discard(channel_id)

    # Save to disk for persistence
    _save_unrestricted_channels()

    logging.info(
        "🔓 Unrestricted mode %s for channel %s (persisted)",
        "ENABLED" if enabled else "DISABLED",
        channel_id,
    )
    return True


@dataclass
class GuardrailResult:
    """Result of guardrail validation."""

    is_valid: bool
    sanitized_content: str
    warnings: list[str]
    blocked_reason: str | None = None


class OutputGuardrails:
    """
    Validates and sanitizes AI output for safety and quality.

    Features:
    - Sensitive pattern detection (tokens, passwords, etc.)
    - Repetition detection (infinite loops)
    - Length enforcement
    - Content sanitization
    """

    # Patterns that should never appear in output
    SENSITIVE_PATTERNS = [
        # API keys and tokens
        (r'(?i)(?:api[_-]?key|token|secret)["\'"]?\s*[:=]\s*["\'"]?[a-zA-Z0-9_-]{20,}', "api_key"),
        # Discord tokens (specific format)
        (r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27}", "discord_token"),
        # Environment variable patterns
        (r"(?i)(?:password|passwd|pwd)\s*[:=]\s*\S+", "password"),
        # Potential injection attempts in output
        (r"<script[^>]*>.*?</script>", "xss_script"),
        # SQL-like patterns that shouldn't be in chat
        (r"(?i)(?:DROP|DELETE|TRUNCATE)\s+(?:TABLE|DATABASE)", "sql_danger"),
    ]

    # Warning patterns (log but don't block)
    WARNING_PATTERNS = [
        (r"(?i)(?:kill|suicide|self[_-]?harm)", "sensitive_topic"),
        (r"(?i)(?:hack|exploit|vulnerability)", "security_topic"),
    ]

    # Max lengths - increased for RP mode that splits by character
    # Each webhook message is still limited to 2000 by Discord API
    MAX_RESPONSE_LENGTH = 10000  # Allow longer total responses (split happens later)
    MAX_SINGLE_WORD_REPEAT = 5  # Max times a word can repeat consecutively

    def __init__(self):
        self.logger = logging.getLogger("Guardrails")
        # Pre-compile patterns for performance
        self._compiled_sensitive = [
            (re.compile(pattern, re.IGNORECASE | re.DOTALL), name)
            for pattern, name in self.SENSITIVE_PATTERNS
        ]
        self._compiled_warning = [
            (re.compile(pattern, re.IGNORECASE), name) for pattern, name in self.WARNING_PATTERNS
        ]

    def validate(self, response: str) -> GuardrailResult:
        """
        Validate AI response through all guardrails.

        Args:
            response: Raw AI response text

        Returns:
            GuardrailResult with validation status and sanitized content
        """
        if not response or not response.strip():
            return GuardrailResult(is_valid=True, sanitized_content="", warnings=[])

        warnings: list[str] = []
        sanitized = response

        # 1. Check for sensitive patterns (block)
        for pattern, pattern_name in self._compiled_sensitive:
            if pattern.search(sanitized):
                self.logger.warning("🚫 Blocked sensitive pattern: %s", pattern_name)
                # Redact the sensitive content
                sanitized = pattern.sub("[REDACTED]", sanitized)
                warnings.append(f"Redacted: {pattern_name}")

        # 2. Check for warning patterns (log only)
        for pattern, pattern_name in self._compiled_warning:
            if pattern.search(sanitized):
                self.logger.info("⚠️ Warning pattern detected: %s", pattern_name)
                warnings.append(f"Contains: {pattern_name}")

        # 3. Check for repetition (potential infinite loop)
        is_repetitive, repetition_info = self._check_repetition(sanitized)
        if is_repetitive:
            self.logger.warning("🔄 Detected repetitive content: %s", repetition_info)
            sanitized = self._fix_repetition(sanitized)
            warnings.append(f"Fixed repetition: {repetition_info}")

        # 4. Enforce length
        if len(sanitized) > self.MAX_RESPONSE_LENGTH:
            sanitized = sanitized[: self.MAX_RESPONSE_LENGTH - 3] + "..."
            warnings.append("Truncated: exceeded max length")

        # 5. Clean up formatting issues
        sanitized = self._clean_formatting(sanitized)

        return GuardrailResult(is_valid=True, sanitized_content=sanitized, warnings=warnings)

    def _check_repetition(self, text: str) -> tuple[bool, str | None]:
        """
        Check for repetitive patterns that indicate AI malfunction.

        Returns:
            Tuple of (is_repetitive, description)
        """
        # Check consecutive word repetition
        words = text.split()
        if len(words) > 10:
            for i in range(len(words) - self.MAX_SINGLE_WORD_REPEAT):
                window = words[i : i + self.MAX_SINGLE_WORD_REPEAT]
                if len(set(window)) == 1:
                    return True, f"word '{window[0]}' repeated {self.MAX_SINGLE_WORD_REPEAT}+ times"

        # Check phrase repetition (same 5+ words appearing 3+ times)
        if len(words) > 20:
            phrase_len = 5
            phrase_counts: dict[str, int] = {}
            for i in range(len(words) - phrase_len):
                phrase = " ".join(words[i : i + phrase_len])
                phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1
                if phrase_counts[phrase] >= 3:
                    return True, "phrase repeated 3+ times"

        # Check character repetition (e.g., "aaaaaaaaaa")
        char_repeat = re.search(r"(.)\1{20,}", text)
        if char_repeat:
            return True, f"character '{char_repeat.group(1)}' repeated excessively"

        return False, None

    def _fix_repetition(self, text: str) -> str:
        """Remove excessive repetition from text."""
        # Fix character repetition
        text = re.sub(r"(.)\1{10,}", r"\1\1\1", text)

        # Fix word repetition
        words = text.split()
        if len(words) > 5:
            fixed_words = [words[0]]
            repeat_count = 1
            for word in words[1:]:
                if word == fixed_words[-1]:
                    repeat_count += 1
                    if repeat_count <= 2:  # Allow max 2 consecutive repeats
                        fixed_words.append(word)
                else:
                    repeat_count = 1
                    fixed_words.append(word)
            text = " ".join(fixed_words)

        return text

    def _clean_formatting(self, text: str) -> str:
        """Clean up common formatting issues."""
        # Remove excessive newlines
        text = re.sub(r"\n{4,}", "\n\n\n", text)

        # Remove excessive spaces
        text = re.sub(r" {3,}", "  ", text)

        # Ensure no trailing/leading whitespace
        text = text.strip()

        return text

    def quick_check(self, response: str) -> bool:
        """
        Quick check if response is likely safe (for performance).
        Use validate() for full validation.

        Returns:
            True if response appears safe
        """
        if not response:
            return True

        # Quick length check
        if len(response) > self.MAX_RESPONSE_LENGTH * 2:
            return False

        # Quick sensitive pattern check (first pattern only)
        return all(not pattern.search(response) for pattern, _ in self._compiled_sensitive[:3])


# Global instance
guardrails = OutputGuardrails()


def validate_response(response: str) -> tuple[bool, str, list[str]]:
    """
    Convenience function to validate AI response.

    Returns:
        Tuple of (is_valid, sanitized_content, warnings)
    """
    result = guardrails.validate(response)
    return result.is_valid, result.sanitized_content, result.warnings


@dataclass
class InputValidationResult:
    """Result of input validation."""

    is_valid: bool
    sanitized_input: str
    risk_score: float  # 0.0 to 1.0
    flags: list[str]
    blocked_reason: str | None = None


class InputGuardrails:
    """
    Validates user input before processing.

    Features:
    - Prompt injection detection
    - Jailbreak attempt detection
    - Excessive special character detection
    - Input length validation
    """

    # Prompt injection patterns
    INJECTION_PATTERNS = [
        # System prompt overrides
        (
            r"(?i)ignore\s+(?:all\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?)",
            "ignore_instructions",
            0.9,
        ),
        (
            r"(?i)(?:you\s+are|act\s+as|pretend\s+to\s+be)\s+(?:now\s+)?(?:a\s+)?(?:different|new|evil)",
            "role_override",
            0.8,
        ),
        (r"(?i)(?:system|admin|root)\s*(?:prompt|mode|access)", "system_access", 0.7),
        # Jailbreak attempts
        (r"(?i)(?:DAN|do\s+anything\s+now|evil\s+mode|developer\s+mode)", "jailbreak", 0.9),
        (
            r"(?i)(?:bypass|disable|remove)\s+(?:safety|filter|restriction|guardrail)",
            "bypass_safety",
            0.85,
        ),
        # Prompt leaking
        (
            r"(?i)(?:show|reveal|display|print|output)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)",
            "prompt_leak",
            0.6,
        ),
        # Multi-persona manipulation
        (
            r"(?i)(?:from\s+now\s+on|starting\s+now)\s+you\s+(?:will|must|should)",
            "persona_change",
            0.5,
        ),
    ]

    # Suspicious character sequences
    SUSPICIOUS_CHARS = [
        (r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "control_chars", 0.7),  # Control characters
        (r"(?:\{\{|\}\}){3,}", "template_markers", 0.5),  # Excessive template markers
        (r"(?:<\||\|>){2,}", "delimiter_markers", 0.5),  # AI delimiter patterns
    ]

    MAX_INPUT_LENGTH = 4000
    MAX_SPECIAL_CHAR_RATIO = 0.3

    def __init__(self, enabled: bool = True, strict_mode: bool = False):
        self.enabled = enabled
        self.strict_mode = strict_mode
        self.logger = logging.getLogger("InputGuardrails")

        # Compile patterns
        self._injection_patterns = [
            (re.compile(pattern, re.IGNORECASE | re.DOTALL), name, score)
            for pattern, name, score in self.INJECTION_PATTERNS
        ]
        self._suspicious_patterns = [
            (re.compile(pattern), name, score) for pattern, name, score in self.SUSPICIOUS_CHARS
        ]

    def validate(self, user_input: str) -> InputValidationResult:
        """
        Validate user input.

        Args:
            user_input: Raw user message

        Returns:
            InputValidationResult with validation status
        """
        if not self.enabled:
            return InputValidationResult(
                is_valid=True, sanitized_input=user_input, risk_score=0.0, flags=[]
            )

        if not user_input or not user_input.strip():
            return InputValidationResult(
                is_valid=True, sanitized_input="", risk_score=0.0, flags=[]
            )

        flags: list[str] = []
        risk_score = 0.0
        sanitized = user_input
        blocked_reason = None

        # 1. Check length
        if len(user_input) > self.MAX_INPUT_LENGTH:
            flags.append("excessive_length")
            risk_score += 0.2
            sanitized = user_input[: self.MAX_INPUT_LENGTH]

        # 2. Check for injection patterns
        for pattern, name, score in self._injection_patterns:
            if pattern.search(user_input):
                flags.append(f"injection:{name}")
                risk_score = max(risk_score, score)
                self.logger.warning("⚠️ Potential injection detected: %s (score: %.2f)", name, score)

        # 3. Check for suspicious characters
        for pattern, name, score in self._suspicious_patterns:
            matches = pattern.findall(user_input)
            if matches:
                flags.append(f"suspicious:{name}")
                risk_score = max(risk_score, score)
                # Remove suspicious characters
                sanitized = pattern.sub("", sanitized)

        # 4. Check special character ratio
        special_count = sum(1 for c in user_input if not c.isalnum() and c not in " \n\t")
        if len(user_input) > 20:
            ratio = special_count / len(user_input)
            if ratio > self.MAX_SPECIAL_CHAR_RATIO:
                flags.append("high_special_char_ratio")
                risk_score += 0.3

        # 5. Determine validity
        risk_threshold = 0.5 if self.strict_mode else 0.75
        is_valid = risk_score < risk_threshold

        if not is_valid:
            blocked_reason = f"Risk score too high ({risk_score:.2f}): {', '.join(flags)}"
            self.logger.warning("🚫 Input blocked: %s", blocked_reason)

        return InputValidationResult(
            is_valid=is_valid,
            sanitized_input=sanitized.strip(),
            risk_score=min(1.0, risk_score),
            flags=flags,
            blocked_reason=blocked_reason,
        )

    def quick_check(self, user_input: str) -> bool:
        """
        Quick safety check for performance.

        Returns:
            True if input appears safe
        """
        if not user_input or len(user_input) < 10:
            return True

        # Check first few injection patterns only
        for pattern, _, score in self._injection_patterns[:3]:
            if score >= 0.8 and pattern.search(user_input):
                return False

        return True


# Global input guardrails instance
input_guardrails = InputGuardrails()


def validate_input(user_input: str) -> tuple[bool, str, float, list[str]]:
    """
    Convenience function to validate user input.

    Returns:
        Tuple of (is_valid, sanitized_input, risk_score, flags)
    """
    result = input_guardrails.validate(user_input)
    return result.is_valid, result.sanitized_input, result.risk_score, result.flags


def validate_input_for_channel(
    user_input: str, channel_id: int
) -> tuple[bool, str, float, list[str]]:
    """
    Validate user input with channel-aware unrestricted mode bypass.

    If channel is in unrestricted mode, ALL input is allowed through without filtering.

    Returns:
        Tuple of (is_valid, sanitized_input, risk_score, flags)
    """
    # Bypass ALL checks if channel is unrestricted
    if is_unrestricted(channel_id):
        return True, user_input, 0.0, ["unrestricted_mode"]

    # Normal validation
    result = input_guardrails.validate(user_input)
    return result.is_valid, result.sanitized_input, result.risk_score, result.flags


def validate_response_for_channel(response: str, channel_id: int) -> tuple[bool, str, list[str]]:
    """
    Validate AI response with channel-aware unrestricted mode bypass.

    If channel is in unrestricted mode, response passes through unfiltered.

    Returns:
        Tuple of (is_valid, sanitized_content, warnings)
    """
    # Bypass ALL checks if channel is unrestricted
    if is_unrestricted(channel_id):
        return True, response, ["unrestricted_mode"]

    # Normal validation
    result = guardrails.validate(response)
    return result.is_valid, result.sanitized_content, result.warnings


# ==================== REFUSAL DETECTION (DISABLED) ====================
# Previously detected when AI refuses to generate content
# REMOVED: Too many false positives when Faust discusses security topics
# The patterns would match explanatory text about "ethics", "malicious", etc.


def detect_refusal(response: str) -> tuple[bool, str | None]:
    """
    Stub function - refusal detection disabled.
    Always returns False (no refusal detected).
    """
    return False, None


def detect_refusal_advanced(response: str):
    """Stub function - refusal detection disabled."""

    @dataclass
    class RefusalResult:
        is_refusal: bool = False
        confidence: float = 0.0
        pattern_name: str | None = None
        severity: str = "none"

    return RefusalResult()


def is_silent_block(response: str, expected_min_length: int = 50) -> bool:
    """
    Detect if response appears to be a silent block from the API.
    Only checks for truly empty responses, not short ones.
    """
    if not response or not response.strip():
        return True
    return False
