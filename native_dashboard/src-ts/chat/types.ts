/**
 * Shared chat-layer types.
 *
 * Extracted from `chat-manager.ts` so other chat-area modules (formatter,
 * search, prism, export picker) can import without a circular dependency on
 * the huge ChatManager class.
 */

export interface ChatConversation {
    id: string;
    title: string | null;
    role_preset: string;
    role_name?: string;
    role_emoji?: string;
    role_color?: string;
    thinking_enabled: boolean;
    is_starred: boolean;
    message_count?: number;
    created_at: string;
    updated_at?: string;
    ai_provider?: string;
    tags?: string[];   // #22 — per-conversation tag list
}

export interface ChatMessage {
    id?: number;
    role: 'user' | 'assistant';
    content: string;
    created_at: string;
    images?: string[];   // Base64 encoded images
    thinking?: string;   // AI thought process
    mode?: string;       // Mode used (Thinking, Unrestricted, etc.)
    is_pinned?: boolean; // Marked important by user (#20)
    liked?: boolean;     // User hit ❤️ on this message (#20b)
}

export interface RolePreset {
    name: string;
    emoji: string;
    color: string;
}

export interface Memory {
    id: string;
    content: string;
    category: string;
    created_at: string;
}

export interface NativeConversationDetail {
    conversation: ChatConversation;
    messages: ChatMessage[];
}
