"""
Memory Commands Cog.
Provides user-facing commands for memory management.
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands
from discord.ext.commands import Context

from utils.color_config import Colors


class MemoryCommands(commands.Cog):
    """
    Commands for managing AI memory.

    Commands:
    - !remember <fact> - Save a fact permanently
    - !forget <fact> - Remove a saved fact
    - !memories - View saved memories
    - !consolidate - Force memory consolidation
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.logger = logging.getLogger("MemoryCommands")

    @commands.command(name="remember")
    async def remember_fact(self, ctx: Context, *, fact: str) -> None:
        """
        Save something to permanent memory.

        Usage: !remember I am allergic to peanuts
        """
        if not fact or len(fact) < 3:
            await ctx.send("❌ กรุณาระบุสิ่งที่ต้องการจำ เช่น `!remember ผมชื่อ John`")
            return

        if len(fact) > 500:
            await ctx.send("❌ ข้อความยาวเกินไป (สูงสุด 500 ตัวอักษร)")
            return

        try:
            from cogs.ai_core.memory.long_term_memory import long_term_memory

            result = await long_term_memory.add_explicit_fact(
                user_id=ctx.author.id, content=fact, channel_id=ctx.channel.id
            )

            if result:
                embed = discord.Embed(
                    title="✅ จำแล้ว!", description=f"```{fact}```", color=Colors.SUCCESS
                )
                embed.set_footer(text="ข้อมูลนี้จะถูกจำอย่างถาวร")
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ ไม่สามารถบันทึกได้ ลองอีกครั้ง")

        except ImportError:
            await ctx.send("❌ ระบบความจำยังไม่พร้อมใช้งาน")
        except Exception as e:
            self.logger.error("Remember command error: %s", e)
            await ctx.send(f"❌ เกิดข้อผิดพลาด: {e}")

    @commands.command(name="forget")
    async def forget_fact(self, ctx: Context, *, query: str) -> None:
        """
        Forget something from memory.

        Usage: !forget allergic to peanuts
        """
        if not query:
            await ctx.send("❌ กรุณาระบุสิ่งที่ต้องการลืม เช่น `!forget แพ้ถั่ว`")
            return

        try:
            from cogs.ai_core.memory.long_term_memory import long_term_memory

            success = await long_term_memory.forget_fact(user_id=ctx.author.id, content_query=query)

            if success:
                embed = discord.Embed(
                    title="🗑️ ลืมแล้ว!", description=f"ลบข้อมูลที่เกี่ยวกับ: `{query}`", color=Colors.WARNING
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"❓ ไม่พบข้อมูลที่ตรงกับ: `{query}`")

        except ImportError:
            await ctx.send("❌ ระบบความจำยังไม่พร้อมใช้งาน")
        except Exception as e:
            self.logger.error("Forget command error: %s", e)
            await ctx.send(f"❌ เกิดข้อผิดพลาด: {e}")

    @commands.command(name="memories", aliases=["mymemory", "facts"])
    async def view_memories(self, ctx: Context, category: str | None = None) -> None:
        """
        View your saved memories.

        Usage:
        - !memories - View all
        - !memories preference - View preferences only
        - !memories identity - View identity facts
        """
        try:
            from cogs.ai_core.memory.long_term_memory import long_term_memory

            facts = await long_term_memory.get_user_facts(user_id=ctx.author.id, category=category)

            if not facts:
                embed = discord.Embed(
                    title="📭 ไม่มีความจำที่บันทึกไว้",
                    description="ใช้ `!remember <fact>` เพื่อบันทึกข้อมูล",
                    color=Colors.INFO,
                )
                await ctx.send(embed=embed)
                return

            embed = discord.Embed(
                title=f"🧠 ความจำของ {ctx.author.display_name}", color=Colors.PRIMARY
            )

            # Group by category
            categories = {}
            for fact in facts:
                cat = fact.category
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append(fact)

            # Category emoji mapping
            cat_emoji = {
                "identity": "👤",
                "preference": "❤️",
                "personal": "📋",
                "relationship": "👥",
                "skill": "💡",
                "custom": "📝",
            }

            for cat, cat_facts in categories.items():
                emoji = cat_emoji.get(cat, "📌")
                value_lines = []

                for fact in cat_facts[:5]:  # Limit 5 per category
                    confidence_icon = "✓" if fact.confidence > 0.7 else "?"
                    mention_info = f"(x{fact.mention_count})" if fact.mention_count > 1 else ""
                    value_lines.append(f"{confidence_icon} {fact.content[:80]} {mention_info}")

                if len(cat_facts) > 5:
                    value_lines.append(f"... และอีก {len(cat_facts) - 5} รายการ")

                embed.add_field(
                    name=f"{emoji} {cat.upper()}",
                    value="\n".join(value_lines) or "ว่าง",
                    inline=False,
                )

            embed.set_footer(text=f"รวม {len(facts)} รายการ | ใช้ !forget <text> เพื่อลบ")
            await ctx.send(embed=embed)

        except ImportError:
            await ctx.send("❌ ระบบความจำยังไม่พร้อมใช้งาน")
        except Exception as e:
            self.logger.error("Memories command error: %s", e)
            await ctx.send(f"❌ เกิดข้อผิดพลาด: {e}")

    @commands.command(name="consolidate")
    @commands.is_owner()
    async def force_consolidate(self, ctx: Context) -> None:
        """
        Force memory consolidation for this channel.
        Owner only.
        """
        try:
            from cogs.ai_core.memory.memory_consolidator import memory_consolidator

            status_msg = await ctx.send("⏳ กำลังรวบรวมความจำ...")

            result = await memory_consolidator.consolidate_channel(
                channel_id=ctx.channel.id, force=True
            )

            if result:
                embed = discord.Embed(
                    title="✅ รวบรวมความจำสำเร็จ",
                    description=f"สรุป {result.message_count} ข้อความเป็นสรุป",
                    color=Colors.SUCCESS,
                )
                embed.add_field(
                    name="📝 สรุป",
                    value=result.summary[:500] if result.summary else "ไม่มี",
                    inline=False,
                )
                if result.key_topics:
                    embed.add_field(
                        name="🏷️ หัวข้อ", value=", ".join(result.key_topics[:5]), inline=False
                    )
                await status_msg.edit(content=None, embed=embed)
            else:
                await status_msg.edit(content="❌ ไม่มีข้อความเพียงพอสำหรับการรวบรวม")

        except ImportError:
            await ctx.send("❌ ระบบ consolidation ยังไม่พร้อมใช้งาน")
        except Exception as e:
            self.logger.error("Consolidate command error: %s", e)
            await ctx.send(f"❌ เกิดข้อผิดพลาด: {e}")

    @commands.command(name="memory_stats")
    @commands.is_owner()
    async def memory_stats(self, ctx: Context) -> None:
        """Show memory system statistics. Owner only."""
        try:
            from cogs.ai_core.memory.long_term_memory import long_term_memory
            from cogs.ai_core.memory.memory_consolidator import memory_consolidator

            embed = discord.Embed(title="📊 Memory System Statistics", color=Colors.INFO)

            # Count facts
            if hasattr(long_term_memory, "_cache"):
                total_facts = sum(len(f) for f in long_term_memory._cache.values())
                embed.add_field(
                    name="📚 Long-term Facts (Cache)",
                    value=f"```{total_facts} facts```",
                    inline=True,
                )

            # Get user's facts
            user_facts = await long_term_memory.get_user_facts(ctx.author.id)
            embed.add_field(
                name="👤 Your Facts", value=f"```{len(user_facts)} facts```", inline=True
            )

            # Get channel summaries
            summaries = await memory_consolidator.get_channel_summaries(ctx.channel.id)
            embed.add_field(
                name="📦 Channel Summaries", value=f"```{len(summaries)} summaries```", inline=True
            )

            await ctx.send(embed=embed)

        except ImportError as e:
            await ctx.send(f"❌ ระบบยังไม่พร้อม: {e}")
        except Exception as e:
            self.logger.error("Memory stats error: %s", e)
            await ctx.send(f"❌ เกิดข้อผิดพลาด: {e}")


async def setup(bot: commands.Bot) -> None:
    """Load the MemoryCommands cog."""
    await bot.add_cog(MemoryCommands(bot))
