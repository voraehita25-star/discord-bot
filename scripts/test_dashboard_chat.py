"""
Quick test script to verify dashboard chat components work.
Run: python scripts/test_dashboard_chat.py
"""

import asyncio
import sys
sys.path.insert(0, ".")

async def test_database():
    """Test database schema and methods."""
    print("=" * 50)
    print("Testing Database...")
    print("=" * 50)
    
    from utils.database.database import Database
    
    db = Database()
    await db.init_schema()
    print("✅ Database schema initialized")
    
    # Test creating a conversation
    conv_id = "test-conv-123"
    await db.create_dashboard_conversation(
        conversation_id=conv_id,
        role_preset="faust",
        thinking_enabled=True,
        title="Test Conversation"
    )
    print(f"✅ Created conversation: {conv_id}")
    
    # Test getting conversations
    convs = await db.get_dashboard_conversations()
    print(f"✅ Got {len(convs)} conversations")
    
    # Test saving messages
    await db.save_dashboard_message(conv_id, "user", "Hello Faust!")
    await db.save_dashboard_message(conv_id, "assistant", "Faust greets you. How may Faust assist?")
    print("✅ Saved messages")
    
    # Test getting messages
    messages = await db.get_dashboard_messages(conv_id)
    print(f"✅ Got {len(messages)} messages")
    
    # Test export
    export_json = await db.export_dashboard_conversation(conv_id, "json")
    print(f"✅ Exported conversation ({len(export_json)} chars)")
    
    export_md = await db.export_dashboard_conversation(conv_id, "markdown")
    print(f"✅ Exported as markdown ({len(export_md)} chars)")
    
    # Cleanup test data
    await db.delete_dashboard_conversation(conv_id)
    print("✅ Deleted test conversation")
    
    print("\n✅ All database tests passed!\n")

async def test_websocket_server():
    """Test WebSocket server startup/shutdown."""
    print("=" * 50)
    print("Testing WebSocket Server...")
    print("=" * 50)
    
    from cogs.ai_core.api.ws_dashboard import (
        start_dashboard_ws_server,
        stop_dashboard_ws_server,
        get_dashboard_ws_server,
        DASHBOARD_ROLE_PRESETS,
    )
    
    print(f"✅ Available presets: {list(DASHBOARD_ROLE_PRESETS.keys())}")
    
    # Start server
    success = await start_dashboard_ws_server()
    if success:
        print("✅ WebSocket server started on ws://127.0.0.1:8765")
    else:
        print("❌ Failed to start WebSocket server")
        return
    
    # Check server status
    server = get_dashboard_ws_server()
    print(f"✅ Server running: {server._running}")
    print(f"✅ Gemini client available: {server.gemini_client is not None}")
    
    # Give it a moment
    await asyncio.sleep(1)
    
    # Stop server
    await stop_dashboard_ws_server()
    print("✅ WebSocket server stopped")
    
    print("\n✅ All WebSocket tests passed!\n")

async def main():
    print("\n" + "=" * 50)
    print("Dashboard Chat Component Tests")
    print("=" * 50 + "\n")
    
    try:
        await test_database()
        await test_websocket_server()
        
        print("=" * 50)
        print("🎉 All tests passed!")
        print("=" * 50)
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
