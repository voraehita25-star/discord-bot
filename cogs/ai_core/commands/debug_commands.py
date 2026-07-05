"""
AI Debug Commands Module
Provides debug commands for AI system observability.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

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
                except (ImportError, AttributeError, TypeError, KeyError):
                    # estimate_tokens อาจล้มตอน runtime ถ้า history entry ผิดรูป
                    # (TypeError/KeyError) ไม่ใช่แค่ ImportError — degrade ลง rough
                    # estimate แทนที่จะให้ทั้งคำสั่ง !ai_debug ล้ม (ตาม Cache/RAG panel)
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

        # 3. RAG System Status
        try:
            from cogs.ai_core.memory.rag import rag_system

            rag_stats = rag_system.get_stats()
            index_status = (
                f"✅ {rag_stats['index_size']} vectors"
                if rag_stats["index_built"]
                else "❌ Not built"
            )
            rag_info = (
                f"FAISS: {'✅' if rag_stats['faiss_available'] else '❌'}\n"
                f"Index: {index_status}\n"
                f"Cache: {rag_stats['memories_cached']} items"
            )
        except ImportError:
            rag_info = "RAG not available"
        except (AttributeError, KeyError, TypeError) as e:
            # Don't let a RAG stats schema drift (missing/renamed key) or a
            # partially-initialized rag_system abort the whole !ai_debug command
            # — degrade just this panel (mirrors the Cache panel's hardening).
            self.logger.debug("RAG stats panel unavailable: %s", e)
            rag_info = "RAG stats unavailable"

        embed.add_field(name="🧠 RAG Memory", value=f"```\n{rag_info}```", inline=True)

        # 4. Performance Stats (if available)
        if chat_manager:
            perf = chat_manager.get_performance_stats()
            if perf:
                perf_lines = []
                for key, data in perf.items():
                    # ใช้ .get() กันค่า perf dict ที่ผิดรูป (missing/renamed key)
                    # ไม่ให้ KeyError ล้มทั้งคำสั่ง !ai_debug — ให้ panel นี้ degrade เอง
                    if data.get("count", 0) > 0:
                        perf_lines.append(f"{key}: {data.get('avg_ms', 0.0):.0f}ms avg")
                if perf_lines:
                    embed.add_field(
                        name="⚡ Performance",
                        value="```\n" + "\n".join(perf_lines[:5]) + "```",
                        inline=False,
                    )

        # 5. Intent Detection (last message simulation)
        try:
            from cogs.ai_core.processing.intent_detector import detect_intent

            # ``resolved`` may be a ``DeletedReferencedMessage`` (the
            # original was deleted between reply and command), which
            # has no ``.content`` attribute and would AttributeError
            # past the ``cast``. Use ``isinstance(..., discord.Message)``
            # so only a real message slot reaches the ``.content`` path.
            ref_resolved = ctx.message.reference.resolved if ctx.message.reference else None
            if isinstance(ref_resolved, discord.Message):
                test_msg = ref_resolved.content
            else:
                test_msg = "สวัสดี"  # Default test

            result = detect_intent(test_msg)
            intent_info = (
                f"Intent: {result.intent.value}\n"
                f"Confidence: {result.confidence:.2f}\n"
                f"Sub: {result.sub_category or 'N/A'}"
            )
            embed.add_field(name="🎯 Intent Detection", value=f"```\n{intent_info}```", inline=True)
        except ImportError as exc:
            self.logger.debug("Intent detection import failed: %s", exc)

        # 6. Entity Memory (if available)
        try:
            from cogs.ai_core.memory.entity_memory import entity_memory

            # `_cache` is private; treat any non-Sized object the same as
            # missing, so a partially-initialised entity_memory doesn't blow
            # up the debug command with TypeError on len().
            _cache_obj = getattr(entity_memory, "_cache", None)
            # Sized ABC excludes None; explicit None check + Sized cast keeps
            # mypy happy without losing the defensive hasattr guard.
            from collections.abc import Sized

            entity_count = len(cast(Sized, _cache_obj)) if isinstance(_cache_obj, Sized) else 0
            embed.add_field(
                name="👤 Entity Memory",
                value=f"```\nCached: {entity_count} entities```",
                inline=True,
            )
        except ImportError as exc:
            self.logger.debug("Entity memory import failed: %s", exc)

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
            # ใช้ .get() กันค่า perf dict ที่ผิดรูป (missing/renamed key)
            # ไม่ให้ KeyError ล้มทั้งคำสั่ง !ai_perf
            if data.get("count", 0) > 0:
                lines.append(
                    f"**{key}**: {data.get('avg_ms', 0.0):.1f}ms avg "
                    f"(min: {data.get('min_ms', 0.0):.1f}, max: {data.get('max_ms', 0.0):.1f}, "
                    f"n={data.get('count', 0)})"
                )

        await ctx.send("\n".join(lines) if len(lines) > 1 else "No performance data yet")

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
        # Streaming state lives in chat_manager.streaming_enabled (a separate
        # dict), NOT in the per-channel chat dict — chat_data.get() always
        # returned None, so the flag showed ❌ even when streaming was on.
        streaming = "✅" if chat_manager.is_streaming_enabled(channel_id) else "❌"
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

    @commands.command(name="ai_tokens")
    @commands.is_owner()
    async def ai_tokens_cmd(self, ctx: Context) -> None:
        """Show token usage statistics from token tracker."""
        try:
            from cogs.ai_core.cache.token_tracker import token_tracker

            try:
                stats = await token_tracker.get_global_stats()
            except Exception as e:
                self.logger.warning("Failed to fetch token tracker stats: %s", e)
                await ctx.send(f"❌ ดึงสถิติ token ไม่สำเร็จ: {type(e).__name__}")
                return

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
