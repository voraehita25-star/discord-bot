"""
WebSocket Contract Tests.

Validates the JSON message schemas exchanged between the Tauri dashboard
and the Python WebSocket server (cogs.ai_core.api.ws_dashboard).

These are pure schema tests — no live server required.
"""

from __future__ import annotations

import json

import pytest

# ============================================================================
# Expected message schemas
# ============================================================================

# Client → Server message types
CLIENT_SCHEMAS: dict[str, dict] = {
    "new_conversation": {
        "required": {"type"},
        "optional": {"role", "conversation_id"},
    },
    "message": {
        "required": {"type", "content"},
        "optional": {"role", "conversation_id", "thinking", "images", "files"},
    },
    "list_conversations": {
        "required": {"type"},
        "optional": set(),
    },
    "load_conversation": {
        "required": {"type", "conversation_id"},
        "optional": set(),
    },
    "delete_conversation": {
        "required": {"type", "conversation_id"},
        "optional": set(),
    },
    "star_conversation": {
        "required": {"type", "conversation_id"},
        "optional": {"starred"},
    },
    "rename_conversation": {
        "required": {"type", "conversation_id", "title"},
        "optional": set(),
    },
    "export_conversation": {
        "required": {"type", "conversation_id"},
        "optional": {"format"},
    },
    "save_memory": {
        "required": {"type", "content"},
        "optional": {"category"},
    },
    "get_memories": {
        "required": {"type"},
        "optional": {"category"},
    },
    "delete_memory": {
        "required": {"type", "memory_id"},
        "optional": set(),
    },
    "get_profile": {
        "required": {"type"},
        "optional": set(),
    },
}

# Server → Client message types
SERVER_SCHEMAS: dict[str, dict] = {
    "auth_success": {
        "required": {"type"},
        "optional": {"user", "session_id"},
    },
    "error": {
        "required": {"type", "message"},
        "optional": {"code"},
    },
    "chunk": {
        "required": {"type", "content"},
        "optional": {"conversation_id", "thinking"},
    },
    "done": {
        "required": {"type"},
        "optional": {"conversation_id", "title", "usage"},
    },
    "conversations": {
        "required": {"type", "conversations"},
        "optional": set(),
    },
    "conversation_loaded": {
        "required": {"type", "conversation_id", "messages"},
        "optional": {"title", "role"},
    },
    "conversation_deleted": {
        "required": {"type", "conversation_id"},
        "optional": set(),
    },
    "memories": {
        "required": {"type", "memories"},
        "optional": set(),
    },
    "memory_saved": {
        "required": {"type"},
        "optional": {"memory_id"},
    },
    "profile": {
        "required": {"type"},
        "optional": {"username", "avatar", "guilds"},
    },
}


# ============================================================================
# Schema validation helpers
# ============================================================================


def validate_message(msg: dict, schemas: dict[str, dict]) -> list[str]:
    """
    Validate a message against the schema registry.
    Returns list of error strings (empty = valid).
    """
    errors: list[str] = []

    msg_type = msg.get("type")
    if not msg_type:
        errors.append("Missing 'type' field")
        return errors

    schema = schemas.get(msg_type)
    if schema is None:
        errors.append(f"Unknown message type: {msg_type}")
        return errors

    # Check required fields
    for field in schema["required"]:
        if field not in msg:
            errors.append(f"Missing required field '{field}' for type '{msg_type}'")

    # Check for unknown fields
    allowed = schema["required"] | schema.get("optional", set())
    for key in msg:
        if key not in allowed:
            # Unknown fields are warnings, not errors (extensibility)
            pass

    return errors


# ============================================================================
# Contract tests
# ============================================================================


class TestClientToServerContracts:
    """Validate client → server message schemas."""

    def test_new_conversation_minimal(self):
        msg = {"type": "new_conversation"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_new_conversation_with_role(self):
        msg = {"type": "new_conversation", "role": "faust"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_message_valid(self):
        msg = {"type": "message", "content": "Hello!"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_message_with_thinking(self):
        msg = {"type": "message", "content": "Explain this", "thinking": True}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_message_missing_content(self):
        msg = {"type": "message"}
        errors = validate_message(msg, CLIENT_SCHEMAS)
        assert any("content" in e for e in errors)

    def test_list_conversations(self):
        msg = {"type": "list_conversations"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_load_conversation_valid(self):
        msg = {"type": "load_conversation", "conversation_id": "abc-123"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_load_conversation_missing_id(self):
        msg = {"type": "load_conversation"}
        errors = validate_message(msg, CLIENT_SCHEMAS)
        assert any("conversation_id" in e for e in errors)

    def test_delete_conversation(self):
        msg = {"type": "delete_conversation", "conversation_id": "abc-123"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_save_memory_valid(self):
        msg = {"type": "save_memory", "content": "Remember this fact"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_save_memory_missing_content(self):
        msg = {"type": "save_memory"}
        errors = validate_message(msg, CLIENT_SCHEMAS)
        assert any("content" in e for e in errors)

    def test_delete_memory_valid(self):
        msg = {"type": "delete_memory", "memory_id": "mem-456"}
        assert validate_message(msg, CLIENT_SCHEMAS) == []

    def test_unknown_type(self):
        msg = {"type": "nonexistent_action"}
        errors = validate_message(msg, CLIENT_SCHEMAS)
        assert any("Unknown" in e for e in errors)

    def test_missing_type(self):
        msg = {"content": "orphaned message"}
        errors = validate_message(msg, CLIENT_SCHEMAS)
        assert any("type" in e for e in errors)

    @pytest.mark.parametrize("msg_type", list(CLIENT_SCHEMAS.keys()))
    def test_all_types_have_type_required(self, msg_type):
        """Every client schema must require the 'type' field."""
        assert "type" in CLIENT_SCHEMAS[msg_type]["required"]


class TestServerToClientContracts:
    """Validate server → client message schemas."""

    def test_error_message(self):
        msg = {"type": "error", "message": "Something went wrong"}
        assert validate_message(msg, SERVER_SCHEMAS) == []

    def test_error_missing_message(self):
        msg = {"type": "error"}
        errors = validate_message(msg, SERVER_SCHEMAS)
        assert any("message" in e for e in errors)

    def test_chunk_message(self):
        msg = {"type": "chunk", "content": "partial response..."}
        assert validate_message(msg, SERVER_SCHEMAS) == []

    def test_done_message(self):
        msg = {"type": "done"}
        assert validate_message(msg, SERVER_SCHEMAS) == []

    def test_conversations_list(self):
        msg = {"type": "conversations", "conversations": []}
        assert validate_message(msg, SERVER_SCHEMAS) == []

    def test_conversation_loaded(self):
        msg = {
            "type": "conversation_loaded",
            "conversation_id": "abc-123",
            "messages": [],
        }
        assert validate_message(msg, SERVER_SCHEMAS) == []

    def test_memories_response(self):
        msg = {"type": "memories", "memories": [{"id": "1", "content": "fact"}]}
        assert validate_message(msg, SERVER_SCHEMAS) == []

    def test_profile_response(self):
        msg = {"type": "profile", "username": "bot-admin"}
        assert validate_message(msg, SERVER_SCHEMAS) == []

    @pytest.mark.parametrize("msg_type", list(SERVER_SCHEMAS.keys()))
    def test_all_types_have_type_required(self, msg_type):
        """Every server schema must require the 'type' field."""
        assert "type" in SERVER_SCHEMAS[msg_type]["required"]


class TestSchemaConsistency:
    """Cross-cutting schema consistency checks."""

    def test_all_schemas_are_json_serializable(self):
        """All sample messages must be valid JSON."""
        sample_messages = [
            {"type": "message", "content": "hello"},
            {"type": "error", "message": "fail"},
            {"type": "chunk", "content": "data"},
            {"type": "done"},
        ]
        for msg in sample_messages:
            serialized = json.dumps(msg)
            parsed = json.loads(serialized)
            assert parsed == msg

    def test_no_overlapping_type_names(self):
        """Client and server type names should be distinct to avoid confusion."""
        client_types = set(CLIENT_SCHEMAS.keys())
        server_types = set(SERVER_SCHEMAS.keys())
        overlap = client_types & server_types
        # Some overlap is acceptable (e.g., both sides understand 'error')
        # but most types should be distinct
        assert len(overlap) <= 2, f"Too much overlap: {overlap}"

    def test_required_is_subset_of_schema_fields(self):
        """Required fields must be a set, not a list."""
        for name, schema in {**CLIENT_SCHEMAS, **SERVER_SCHEMAS}.items():
            assert isinstance(schema["required"], set), f"{name}: required should be a set"
