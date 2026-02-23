"""
AI Debug Commands Module
Provides debug commands for AI system observability.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from discord.ext.commands import Context


class AIDebug(commands.Cog):
    """Debug commands for AI system observability."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.logger = logging.getLogger("AIDebug")

    def _get_chat_manager(self):
        """Get ChatManager from AI cog."""
        ai_cog = self.bot.get_cog("AI")
        if ai_cog and hasattr(ai_cog, "chat_manager"):
            return ai_cog.chat_manager
        return None

    @commands.command(name="ai_debug")
    @commands.is_owner()
    async def ai_debug(self, ctx: Context) -> None:
        """
        Show AI system debug information.

        Displays:
        - Context size (tokens)
        - Cache statistics
        - RAG system status
        - Current session info
        """
        embed = discord.Embed(title="🔧 AI Debug Information", color=discord.Color.blue())

        channel_id = ctx.channel.id
        chat_manager = self._get_chat_manager()

        # 1. Session Info
        session_info = "❌ No session"
        token_count = 0
        thinking_enabled = False

        if chat_manager:
            chat_data = chat_manager.chats.get(channel_id)
            if chat_data:
                history = chat_data.get("history", [])
                thinking_enabled = chat_data.get("thinking_enabled", True)
                session_info = f"✅ Active ({len(history)} messages)"

                # Estimate tokens using history_manager
                try:
                    from cogs.ai_core.memory.history_manager import history_manager

                    token_count = history_manager.estimate_tokens(history)
                except ImportError:
                    token_count = len(history) * 50  # Rough estimate

        embed.add_field(
            name="📝 Session",
            value=(
                f"```\n{session_info}\n"
                f"Tokens: ~{token_count:,}\n"
                f"Thinking: {'✅' if thinking_enabled else '❌'}```"
            ),
            inline=True,
        )

        # 2. Cache Stats
        try:
            from cogs.ai_core.cache.ai_cache import ai_cache

            stats = ai_cache.get_stats()
            cache_info = (
                f"Entries: {stats.total_entries}\n"
                f"Hits: {stats.hits} ({stats.hit_rate:.1%})\n"
                f"Semantic: {stats.semantic_hits}\n"
                f"Memory: {stats.memory_estimate_kb:.1f}KB"
            )
        except ImportError:
            cache_info = "Cache not available"

        embed.add_field(name="💾 Cache", value=f"```\n{cache_info}```", inline=True)

        # 3. RAG System Status
        try:
            from cogs.ai_core.memory.rag import rag_system

            stats = rag_system.get_stats()
            index_status = (
                f"✅ {stats['index_size']} vectors" if stats["index_built"] else "❌ Not built"
            )
            rag_info = (
                f"FAISS: {'✅' if stats['faiss_available'] else '❌'}\n"
                f"Index: {index_status}\n"
                f"Cache: {stats['memories_cached']} items"
            )
        except ImportError:
            rag_info = "RAG not available"

        embed.add_field(name="🧠 RAG Memory", value=f"```\n{rag_info}```", inline=True)

        # 4. Performance Stats (if available)
        if chat_manager:
            perf = chat_manager.get_performance_stats()
            if perf:
                perf_lines = []
                for key, data in perf.items():
                    if data["count"] > 0:
                        perf_lines.append(f"{key}: {data['avg_ms']:.0f}ms avg")
                if perf_lines:
                    embed.add_field(
                        name="⚡ Performance",
                        value="```\n" + "\n".join(perf_lines[:5]) + "```",
                        inline=False,
                    )

        # 5. Intent Detection (last message simulation)
        try:
            from cogs.ai_core.processing.intent_detector import detect_intent

            if ctx.message.reference and ctx.message.reference.resolved:
                test_msg = ctx.message.reference.resolved.content
            else:
                test_msg = "สวัสดี"  # Default test

            result = detect_intent(test_msg)
            intent_info = (
                f"Intent: {result.intent.value}\n"
                f"Confidence: {result.confidence:.2f}\n"
                f"Sub: {result.sub_category or 'N/A'}"
            )
            embed.add_field(name="🎯 Intent Detection", value=f"```\n{intent_info}```", inline=True)
        except ImportError:
            pass

        # 6. Entity Memory (if available)
        try:
            from cogs.ai_core.memory.entity_memory import entity_memory

            entity_count = len(entity_memory._cache) if hasattr(entity_memory, "_cache") else 0
            embed.add_field(
                name="👤 Entity Memory",
                value=f"```\nCached: {entity_count} entities```",
                inline=True,
            )
        except ImportError:
            pass

        embed.set_footer(text=f"Channel ID: {channel_id}")

        await ctx.send(embed=embed)

    @commands.command(name="ai_perf")
    @commands.is_owner()
    async def ai_perf(self, ctx: Context) -> None:
        """Show detailed AI performance metrics."""
        chat_manager = self._get_chat_manager()

        if not chat_manager:
            await ctx.send("❌ AI system not available")
            return

        perf = chat_manager.get_performance_stats()

        lines = ["**⚡ AI Performance Metrics**\n"]
        for key, data in perf.items():
            if data["count"] > 0:
                lines.append(
                    f"**{key}**: {data['avg_ms']:.1f}ms avg "
                    f"(min: {data['min_ms']:.1f}, max: {data['max_ms']:.1f}, "
                    f"n={data['count']})"
                )

        await ctx.send("\n".join(lines) if len(lines) > 1 else "No performance data yet")

    @commands.command(name="ai_cache_clear")
    @commands.is_owner()
    async def ai_cache_clear(self, ctx: Context) -> None:
        """Clear the AI response cache."""
        try:
            from cogs.ai_core.cache.ai_cache import ai_cache

            count = ai_cache.invalidate()
            await ctx.send(f"✅ Cleared {count} cache entries")
        except ImportError:
            await ctx.send("❌ Cache not available")

    @commands.command(name="ai_trace")
    @commands.is_owner()
    async def ai_trace(self, ctx: Context) -> None:
        """
        Show detailed trace of the last AI request.

        Displays:
        - Prompt sent
        - Tokens used
        - Cache status
        - RAG results
        - Processing stages
        """
        chat_manager = self._get_chat_manager()
        if not chat_manager:
            await ctx.send("❌ AI system not available")
            return

        channel_id = ctx.channel.id
        chat_data = chat_manager.chats.get(channel_id)

        if not chat_data:
            await ctx.send("❌ No active session in this channel")
            return

        # Get last trace if available
        last_trace = chat_data.get("last_trace", {})

        embed = discord.Embed(title="🔍 AI Request Trace", color=discord.Color.blue())

        # Basic info
        thinking = "✅" if chat_data.get("thinking_enabled") else "❌"
        streaming = "✅" if chat_data.get("streaming_enabled") else "❌"
        embed.add_field(
            name="📝 Session Info",
            value=(
                f"```\nMessages: {len(chat_data.get('history', []))}\n"
                f"Thinking: {thinking}\n"
                f"Streaming: {streaming}```"
            ),
            inline=True,
        )

        # Last request timing
        if last_trace:
            timing_info = (
                f"Total: {last_trace.get('total_ms', 0):.0f}ms\n"
                f"API: {last_trace.get('api_ms', 0):.0f}ms\n"
                f"RAG: {last_trace.get('rag_ms', 0):.0f}ms"
            )
            embed.add_field(name="⏱️ Timing", value=f"```\n{timing_info}```", inline=True)

            # Tokens
            input_tokens = last_trace.get("input_tokens", "N/A")
            output_tokens = last_trace.get("output_tokens", "N/A")
            embed.add_field(
                name="🔢 Tokens",
                value=f"```\nInput: {input_tokens}\nOutput: {output_tokens}```",
                inline=True,
            )

            # Cache status
            cache_status = "HIT ✅" if last_trace.get("cache_hit") else "MISS"
            embed.add_field(name="💾 Cache", value=f"```\n{cache_status}```", inline=True)

            # RAG results
            rag_count = last_trace.get("rag_results", 0)
            embed.add_field(name="🧠 RAG", value=f"```\nMemories: {rag_count}```", inline=True)

            # Intent
            intent = last_trace.get("intent", "N/A")
            embed.add_field(name="🎯 Intent", value=f"```\n{intent}```", inline=True)
        else:
            embed.add_field(
                name="ℹ️ Info", value="No trace data available. Make a request first.", inline=False
            )

        embed.set_footer(text=f"Channel: {channel_id}")
        await ctx.send(embed=embed)

    @commands.command(name="ai_stats")
    @commands.is_owner()
    async def ai_stats_cmd(self, ctx: Context) -> None:
        """
        Show comprehensive AI statistics.

        Includes latency percentiles, intent accuracy, and token usage.
        """
        try:
            from cogs.ai_core.cache.analytics import get_detailed_ai_stats

            stats = get_detailed_ai_stats()
        except ImportError:
            await ctx.send("❌ Analytics not available")
            return

        embed = discord.Embed(title="📊 Comprehensive AI Statistics", color=discord.Color.green())

        # Summary
        summary = stats.get("summary", {})
        summary_text = (
            f"Total: {summary.get('total_interactions', 0):,}\n"
            f"Avg Response: {summary.get('avg_response_time_ms', 0):.0f}ms\n"
            f"Cache Rate: {summary.get('cache_hit_rate', 0):.1%}\n"
            f"Error Rate: {summary.get('error_rate', 0):.1%}\n"
            f"Per Hour: {summary.get('interactions_per_hour', 0):.1f}"
        )
        embed.add_field(name="📈 Summary", value=f"```\n{summary_text}```", inline=False)

        # Latency Percentiles
        latency = stats.get("latency_percentiles", {})
        if latency.get("count", 0) > 0:
            latency_text = (
                f"p50: {latency.get('p50', 0):.0f}ms\n"
                f"p95: {latency.get('p95', 0):.0f}ms\n"
                f"p99: {latency.get('p99', 0):.0f}ms\n"
                f"Min: {latency.get('min', 0):.0f}ms\n"
                f"Max: {latency.get('max', 0):.0f}ms"
            )
            embed.add_field(
                name="⏱️ Latency Percentiles", value=f"```\n{latency_text}```", inline=True
            )

        # Token Usage
        tokens = stats.get("tokens", {})
        tokens_text = (
            f"Input: {tokens.get('input', 0):,}\n"
            f"Output: {tokens.get('output', 0):,}\n"
            f"Total: {tokens.get('total', 0):,}"
        )
        embed.add_field(name="🔢 Token Usage (Est.)", value=f"```\n{tokens_text}```", inline=True)

        # Quality
        quality = stats.get("quality", {})
        if quality.get("total_ratings", 0) > 0:
            quality_text = (
                f"Avg Score: {quality.get('average_score', 0):.2f}\n"
                f"👍: {quality.get('positive_reactions', 0)}\n"
                f"👎: {quality.get('negative_reactions', 0)}"
            )
            embed.add_field(name="⭐ Quality", value=f"```\n{quality_text}```", inline=True)

        # Intent Accuracy
        intent = stats.get("intent_accuracy", {})
        if intent.get("total_feedback", 0) > 0:
            intent_text = (
                f"Accuracy: {intent.get('accuracy', 0):.1%}\n"
                f"Feedback: {intent.get('total_feedback', 0)}"
            )
            embed.add_field(name="🎯 Intent Accuracy", value=f"```\n{intent_text}```", inline=True)

        await ctx.send(embed=embed)

    @commands.command(name="ai_tokens")
    @commands.is_owner()
    async def ai_tokens_cmd(self, ctx: Context) -> None:
        """Show token usage statistics from token tracker."""
        try:
            from cogs.ai_core.cache.token_tracker import token_tracker

            stats = await token_tracker.get_global_stats()

            embed = discord.Embed(title="💰 Token Usage Tracker", color=discord.Color.gold())

            embed.add_field(
                name="📊 Global Stats",
                value=(
                    f"```\nRecords: {stats.get('total_records', 0):,}\n"
                    f"Tokens: {stats.get('total_tokens', 0):,}\n"
                    f"Users: {stats.get('unique_users', 0)}\n"
                    f"Channels: {stats.get('unique_channels', 0)}```"
                ),
                inline=False,
            )

            await ctx.send(embed=embed)
        except ImportError:
            await ctx.send("❌ Token tracker not available")


async def setup(bot: commands.Bot) -> None:
    """Load the AIDebug cog."""
    await bot.add_cog(AIDebug(bot))
