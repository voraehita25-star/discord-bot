"""
Character State Tracker
Tracks current state of characters in roleplay scenarios.
Provides real-time context about what characters are doing, where they are, etc.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..data.constants import STATE_CLEANUP_MAX_AGE_HOURS, STATE_CLEANUP_MAX_CHANNELS


@dataclass
class CharacterState:
    """Current state of a character in RP."""

    name: str
    location: str | None = None  # Where they are
    activity: str | None = None  # What they're doing
    emotion: str | None = None  # Current emotional state
    nearby_characters: list[str] = field(default_factory=list)
    inventory: list[str] = field(default_factory=list)  # Items they have
    last_action: str | None = None
    last_dialogue: str | None = None
    updated_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)  # LRU tracking

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {k: v for k, v in asdict(self).items() if v is not None and v != []}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterState:
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_prompt_text(self) -> str:
        """Convert to text for prompt injection."""
        lines = [f"[สถานะปัจจุบันของ {self.name}]"]
        if self.location:
            lines.append(f"- ตำแหน่ง: {self.location}")
        if self.activity:
            lines.append(f"- กำลังทำ: {self.activity}")
        if self.emotion:
            lines.append(f"- อารมณ์: {self.emotion}")
        if self.nearby_characters:
            lines.append(f"- ตัวละครใกล้เคียง: {', '.join(self.nearby_characters)}")
        if self.last_action:
            lines.append(f"- การกระทำล่าสุด: {self.last_action}")
        return "\n".join(lines)


class CharacterStateTracker:
    """
    Tracks and manages character states across RP sessions.

    Features:
    - Real-time state tracking per character per channel
    - Auto-extract state from AI responses
    - State persistence between sessions
    - Memory bounds to prevent unbounded growth
    """

    # Max limits to prevent memory growth
    MAX_CHANNELS = STATE_CLEANUP_MAX_CHANNELS
    MAX_CHARACTERS_PER_CHANNEL = 50

    def __init__(self):
        # States stored per channel: {channel_id: {character_name: CharacterState}}
        self._states: dict[int, dict[str, CharacterState]] = {}
        self._last_scene: dict[int, str] = {}  # Last scene description per channel

    def get_state(self, character_name: str, channel_id: int) -> CharacterState | None:
        """Get current state of a character (updates last_accessed for LRU)."""
        channel_states = self._states.get(channel_id, {})
        state = channel_states.get(character_name)
        if state:
            state.last_accessed = time.time()  # Update access time for LRU
        return state

    def set_state(self, character_name: str, channel_id: int, **kwargs) -> CharacterState:
        """Update character state with provided fields."""
        if channel_id not in self._states:
            # Enforce max channels limit
            if len(self._states) >= self.MAX_CHANNELS:
                # Remove oldest channel by oldest access time (LRU)
                # Filter out channels with empty states to avoid min() on empty sequence
                channels_with_states = [
                    cid for cid in self._states if self._states[cid]
                ]
                if channels_with_states:
                    oldest_channel = min(
                        channels_with_states,
                        key=lambda cid: min(
                            (s.last_accessed for s in self._states[cid].values()),
                            default=0,
                        ),
                    )
                    self._states.pop(oldest_channel, None)
                    self._last_scene.pop(oldest_channel, None)
                # All channels are empty, clear one arbitrarily
                elif self._states:
                    oldest_channel = next(iter(self._states))
                    self._states.pop(oldest_channel, None)
                    self._last_scene.pop(oldest_channel, None)
            self._states[channel_id] = {}

        existing = self._states[channel_id].get(character_name)

        if existing:
            # Update existing state
            for key, value in kwargs.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.updated_at = time.time()
            existing.last_accessed = time.time()  # Also update access time
            return existing
        else:
            # Enforce max characters per channel
            if len(self._states[channel_id]) >= self.MAX_CHARACTERS_PER_CHANNEL:
                # Remove least recently accessed character (LRU)
                oldest_char = min(
                    self._states[channel_id].keys(),
                    key=lambda name: self._states[channel_id][name].last_accessed,
                )
                self._states[channel_id].pop(oldest_char, None)

            # Create new state
            state = CharacterState(name=character_name, **kwargs)
            self._states[channel_id][character_name] = state
            return state

    def update_from_response(self, response_text: str, channel_id: int) -> list[str]:
        """
        Extract and update character states from AI response.
        Returns list of character names that were updated.

        Looks for patterns like:
        - {{CharacterName}} ... action/dialogue
        - Character location mentions
        - Emotion indicators
        """
        updated = []

        # Pattern: {{CharacterName}} followed by content
        character_blocks = re.findall(r"\{\{([^}]+)\}\}(.*?)(?=\{\{|$)", response_text, re.DOTALL)

        for char_name, content in character_blocks:
            char_name = char_name.strip()
            content = content.strip()

            if not char_name or not content:
                continue

            # Extract state information
            state_updates = {}

            # Location detection (Thai patterns)
            location_match = re.search(
                r'(?:อยู่ที่|มาถึง|เดินไป|ยืนอยู่|นั่งอยู่|ที่|ใน)\s*["\']?([^"\',.!?\n]{3,30})["\']?', content
            )
            if location_match:
                state_updates["location"] = location_match.group(1).strip()

            # Activity detection
            activity_match = re.search(r"(?:กำลัง|อยู่|พยายาม)\s*([^,.!?\n]{3,50})", content)
            if activity_match:
                state_updates["activity"] = activity_match.group(1).strip()

            # Emotion detection
            emotion_patterns = {
                "happy": ["ยิ้ม", "หัวเราะ", "ดีใจ", "มีความสุข", "ร่าเริง"],
                "sad": ["เศร้า", "ร้องไห้", "น้ำตา", "เสียใจ"],
                "angry": ["โกรธ", "หงุดหงิด", "โมโห", "ฉุนเฉียว"],
                "embarrassed": ["อาย", "เขิน", "หน้าแดง", "ประหม่า"],
                "scared": ["กลัว", "ตกใจ", "หวาดกลัว", "สะดุ้ง"],
                "confused": ["งง", "สับสน", "มึน"],
                "excited": ["ตื่นเต้น", "ใจเต้น", "ลุ้น"],
            }

            for emotion, patterns in emotion_patterns.items():
                if any(p in content for p in patterns):
                    state_updates["emotion"] = emotion
                    break

            # Extract last dialogue (first quoted text)
            dialogue_match = re.search(r'["\']([^"\']{5,100})["\']', content)
            if dialogue_match:
                state_updates["last_dialogue"] = dialogue_match.group(1)

            # Extract last action (first > marked text)
            action_match = re.search(r">\s*([^<\n]{10,150})", content)
            if action_match:
                state_updates["last_action"] = action_match.group(1).strip()

            # Update state
            if state_updates:
                self.set_state(char_name, channel_id, **state_updates)
                updated.append(char_name)

        return updated

    def get_all_states(self, channel_id: int) -> dict[str, CharacterState]:
        """Get all character states for a channel."""
        return self._states.get(channel_id, {})

    def get_states_for_prompt(
        self, channel_id: int, character_names: list[str] | None = None
    ) -> str:
        """Get formatted state information for prompt injection."""
        states = self.get_all_states(channel_id)

        if not states:
            return ""

        if character_names:
            states = {k: v for k, v in states.items() if k in character_names}

        if not states:
            return ""

        lines = ["[สถานะปัจจุบันของตัวละคร]"]
        for state in states.values():
            lines.append(state.to_prompt_text())
            lines.append("")

        return "\n".join(lines)

    def set_scene(self, channel_id: int, scene: str) -> None:
        """Set the current scene description."""
        self._last_scene[channel_id] = scene

    def get_scene(self, channel_id: int) -> str | None:
        """Get the current scene description."""
        return self._last_scene.get(channel_id)

    def clear_channel(self, channel_id: int) -> None:
        """Clear all states for a channel."""
        if channel_id in self._states:
            del self._states[channel_id]
        if channel_id in self._last_scene:
            del self._last_scene[channel_id]

    def cleanup_old_states(
        self,
        max_age_hours: int = STATE_CLEANUP_MAX_AGE_HOURS,
        max_channels: int = STATE_CLEANUP_MAX_CHANNELS,
    ) -> int:
        """
        Remove states older than max_age_hours and enforce max channel limit.
        Returns number of channels removed.

        Should be called periodically to prevent memory leaks.
        """
        removed = 0
        cutoff = time.time() - (max_age_hours * 3600)

        # Remove old states
        for channel_id in list(self._states.keys()):
            states = self._states.get(channel_id)
            if states is None:
                continue
            # Check if all states are old
            if all(s.updated_at < cutoff for s in states.values()):
                self._states.pop(channel_id, None)
                self._last_scene.pop(channel_id, None)
                removed += 1

        # Enforce max channel limit if still over
        if len(self._states) > max_channels:
            # Sort by least recently accessed (LRU) and remove excess
            sorted_channels = sorted(
                self._states.keys(),
                key=lambda cid: max(
                    (s.last_accessed for s in self._states[cid].values()), default=0
                ),
            )
            excess = len(self._states) - max_channels
            for channel_id in sorted_channels[:excess]:
                self._states.pop(channel_id, None)
                self._last_scene.pop(channel_id, None)
                removed += 1

        return removed

    def to_dict(self, channel_id: int) -> dict[str, Any]:
        """Export channel states to dictionary for persistence."""
        states = self.get_all_states(channel_id)
        return {
            "states": {k: v.to_dict() for k, v in states.items()},
            "scene": self.get_scene(channel_id),
        }

    def from_dict(self, channel_id: int, data: dict[str, Any]) -> None:
        """Import channel states from dictionary."""
        if "states" in data:
            self._states[channel_id] = {
                k: CharacterState.from_dict(v) for k, v in data["states"].items()
            }
        if "scene" in data:
            self._last_scene[channel_id] = data["scene"]


# Global instance
state_tracker = CharacterStateTracker()
