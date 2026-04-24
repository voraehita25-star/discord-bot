"""Tests for shared Claude payload helpers."""

from __future__ import annotations


def test_build_claude_base64_image_block_rejects_unsupported_media_type():
    from cogs.ai_core.claude_payloads import build_claude_base64_image_block

    result = build_claude_base64_image_block("YWJj", "video/mp4")

    assert result is None


def test_build_single_user_text_messages_returns_message_param_shape():
    from cogs.ai_core.claude_payloads import build_single_user_text_messages

    result = build_single_user_text_messages("hello")

    assert result == [{"role": "user", "content": "hello"}]


def test_convert_to_claude_messages_replaces_unsupported_inline_media_with_notice():
    from cogs.ai_core.api.api_handler import convert_to_claude_messages

    result = convert_to_claude_messages([
        {
            "role": "user",
            "parts": [
                {
                    "inline_data": {
                        "mime_type": "video/mp4",
                        "data": "YWJj",
                    }
                }
            ],
        }
    ])

    assert result == [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "[User attached unsupported media omitted: video/mp4]",
                }
            ],
        }
    ]
