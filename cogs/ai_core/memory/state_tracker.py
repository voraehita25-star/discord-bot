"""
Character State Tracker
Tracks current state of characters in roleplay scenarios.
Provides real-time context about what characters are doing, where they are, etc.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


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
    """

    def __init__(self):
        # States stored per channel: {channel_id: {character_name: CharacterState}}
        self._states: dict[int, dict[str, CharacterState]] = {}
        self._last_scene: dict[int, str] = {}  # Last scene description per channel

    def get_state(self, character_name: str, channel_id: int) -> CharacterState | None:
        """Get current state of a character."""
        channel_states = self._states.get(channel_id, {})
        return channel_states.get(character_name)

    def set_state(self, character_name: str, channel_id: int, **kwargs) -> CharacterState:
        """Update character state with provided fields."""
        if channel_id not in self._states:
            self._states[channel_id] = {}

        existing = self._states[channel_id].get(character_name)

        if existing:
            # Update existing state
            for key, value in kwargs.items():
                if hasattr(existing, key) and value is not None:
                    setattr(existing, key, value)
            existing.updated_at = time.time()
            return existing
        else:
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
        import re

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
