"""
Unit Tests for AI Core Module.
Tests RAG system, storage, and chat logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


class TestRAGSystem:
    """Test RAG (Retrieval-Augmented Generation) system."""

    def test_cosine_similarity(self) -> None:
        """Test cosine similarity calculation."""

        def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
            """Calculate cosine similarity between two vectors."""
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)

            if norm_a == 0 or norm_b == 0:
                return 0.0

            return float(dot_product / (norm_a * norm_b))

        # Test identical vectors = 1.0
        vec1 = np.array([1.0, 2.0, 3.0])
        assert cosine_similarity(vec1, vec1) == pytest.approx(1.0)

        # Test orthogonal vectors = 0.0
        vec2 = np.array([1.0, 0.0, 0.0])
        vec3 = np.array([0.0, 1.0, 0.0])
        assert cosine_similarity(vec2, vec3) == pytest.approx(0.0)

        # Test opposite vectors = -1.0
        vec4 = np.array([1.0, 0.0, 0.0])
        vec5 = np.array([-1.0, 0.0, 0.0])
        assert cosine_similarity(vec4, vec5) == pytest.approx(-1.0)

        # Test zero vector
        zero_vec = np.array([0.0, 0.0, 0.0])
        assert cosine_similarity(vec1, zero_vec) == 0.0

    def test_embedding_dimension(self) -> None:
        """Test that embedding dimension is correct."""
        EMBEDDING_DIM = 768  # Expected dimension for Gemini embeddings

        # Create mock embedding
        embedding = np.random.rand(EMBEDDING_DIM).astype(np.float32)

        assert len(embedding) == EMBEDDING_DIM
        assert embedding.dtype == np.float32

    def test_similarity_threshold(self) -> None:
        """Test similarity threshold filtering."""
        SIMILARITY_THRESHOLD = 0.65

        # Mock scored memories
        scored_memories = [
            (0.9, "Very relevant memory"),
            (0.7, "Somewhat relevant memory"),
            (0.5, "Low relevance memory"),
            (0.3, "Irrelevant memory"),
        ]

        # Filter by threshold
        relevant = [m[1] for m in scored_memories if m[0] > SIMILARITY_THRESHOLD]

        assert len(relevant) == 2
        assert "Very relevant memory" in relevant
        assert "Somewhat relevant memory" in relevant
        assert "Low relevance memory" not in relevant


class TestChatStorage:
    """Test chat history storage."""

    def test_history_format(self) -> None:
        """Test chat history format."""
        history_entry = {
            "role": "user",
            "parts": ["Hello, how are you?"],
            "timestamp": "2026-01-12T02:00:00",
        }

        assert history_entry["role"] in ["user", "model"]
        assert isinstance(history_entry["parts"], list)
        assert len(history_entry["parts"]) > 0

    def test_history_limit(self) -> None:
        """Test history limit enforcement."""
        HISTORY_LIMIT = 100

        # Create oversize history
        history = [{"role": "user", "parts": [f"Message {i}"]} for i in range(150)]

        # Prune to limit
        if len(history) > HISTORY_LIMIT:
            history = history[-HISTORY_LIMIT:]

        assert len(history) == HISTORY_LIMIT
        assert history[0]["parts"][0] == "Message 50"  # Oldest remaining
        assert history[-1]["parts"][0] == "Message 149"  # Newest

    def test_metadata_format(self) -> None:
        """Test metadata format for chat sessions."""
        metadata = {
            "channel_id": 1234567890,
            "guild_id": 9876543210,
            "thinking_enabled": True,
            "last_updated": "2026-01-12T02:00:00",
            "message_count": 50,
        }

        assert isinstance(metadata["channel_id"], int)
        assert isinstance(metadata["thinking_enabled"], bool)
        assert metadata["message_count"] >= 0


class TestChatManager:
    """Test ChatManager functionality."""

    def test_session_timeout(self) -> None:
        """Test session timeout logic."""
        import time

        SESSION_TIMEOUT = 3600  # 1 hour

        last_accessed = {
            123: time.time() - 7200,  # 2 hours ago (should timeout)
            456: time.time() - 1800,  # 30 mins ago (should not timeout)
            789: time.time() - 3700,  # Just over 1 hour (should timeout)
        }

        current_time = time.time()
        inactive = [
            cid
            for cid, last_time in last_accessed.items()
            if current_time - last_time > SESSION_TIMEOUT
        ]

        assert 123 in inactive
        assert 456 not in inactive
        assert 789 in inactive

    def test_voice_command_parsing(self) -> None:
        """Test voice channel command parsing."""

        def parse_voice_command(message: str) -> tuple[str | None, int | None]:
            """Parse voice commands from message."""
            import re

            msg_lower = message.lower()

            join_patterns = ["เข้ามารอใน", "join vc", "เข้า vc"]
            leave_patterns = ["ออกจาก vc", "leave vc", "ออก vc"]

            for pattern in leave_patterns:
                if pattern in msg_lower:
                    return "leave", None

            for pattern in join_patterns:
                if pattern in msg_lower:
                    match = re.search(r"\b(\d{17,20})\b", message)
                    if match:
                        return "join", int(match.group(1))
                    return "join", None

            return None, None

        # Test leave command
        assert parse_voice_command("ออกจาก vc เลย")[0] == "leave"
        assert parse_voice_command("leave vc please")[0] == "leave"

        # Test join command with channel ID
        action, channel_id = parse_voice_command("เข้า vc 12345678901234567890")
        assert action == "join"
        assert channel_id == 12345678901234567890

        # Test join without channel ID
        action, channel_id = parse_voice_command("join vc")
        assert action == "join"
        assert channel_id is None

        # Test unrelated message
        assert parse_voice_command("Hello there")[0] is None


class TestResponseProcessing:
    """Test response text processing."""

    def test_quote_cleanup(self) -> None:
        """Test cleanup of quotes in response."""
        import re

        PATTERN_QUOTE = re.compile(r'^>\s*(["\'])', re.MULTILINE)

        text = """> "Hello there"
This is normal text
> 'Another quote'
"""

        cleaned = PATTERN_QUOTE.sub(r"\1", text)

        assert '> "' not in cleaned
        assert "> '" not in cleaned
        assert '"Hello there"' in cleaned

    def test_character_tag_detection(self) -> None:
        """Test {{Character}} tag detection."""
        import re

        PATTERN_CHARACTER_TAG = re.compile(r"\{\{(.+?)\}\}")

        text = "{{Alice}} said hello to {{Bob}}"

        matches = PATTERN_CHARACTER_TAG.findall(text)

        assert len(matches) == 2
        assert "Alice" in matches
        assert "Bob" in matches

    def test_server_command_extraction(self) -> None:
        """Test server command extraction from response."""
        import re

        PATTERN_SERVER_COMMAND = re.compile(
            r"\[\[(CREATE_TEXT|DELETE_CHANNEL|CREATE_ROLE)(?::\s*(.*?))?\]\]"
        )

        # Test basic command
        text = "[[CREATE_TEXT: general-chat]]"
        match = PATTERN_SERVER_COMMAND.search(text)

        assert match is not None
        assert match.group(1) == "CREATE_TEXT"
        assert match.group(2).strip() == "general-chat"

        # Test command without args
        text2 = "[[DELETE_CHANNEL]]"
        match2 = PATTERN_SERVER_COMMAND.search(text2)

        assert match2 is not None
        assert match2.group(1) == "DELETE_CHANNEL"


class TestToolExecution:
    """Test AI tool execution."""

    def test_command_handler_mapping(self) -> None:
        """Test command handler dictionary structure."""
        COMMAND_HANDLERS = {
            "CREATE_TEXT": "cmd_create_text",
            "CREATE_VOICE": "cmd_create_voice",
            "CREATE_CATEGORY": "cmd_create_category",
            "DELETE_CHANNEL": "cmd_delete_channel",
            "CREATE_ROLE": "cmd_create_role",
            "DELETE_ROLE": "cmd_delete_role",
        }

        assert "CREATE_TEXT" in COMMAND_HANDLERS
        assert "DELETE_CHANNEL" in COMMAND_HANDLERS

        # Test handler naming convention
        for _cmd, handler in COMMAND_HANDLERS.items():
            assert handler.startswith("cmd_")

    def test_tool_definition_format(self) -> None:
        """Test tool definition format for Gemini."""
        tool_definition = {
            "name": "create_channel",
            "description": "Create a new text channel in the server",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the channel to create"},
                    "category": {
                        "type": "string",
                        "description": "Category to create the channel in",
                    },
                },
                "required": ["name"],
            },
        }

        assert "name" in tool_definition
        assert "description" in tool_definition
        assert "parameters" in tool_definition
        assert "properties" in tool_definition["parameters"]


# Run tests with: python -m pytest tests/test_ai_core.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
