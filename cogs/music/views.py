# pyright: reportAttributeAccessIssue=false
# pyright: reportArgumentType=false
"""
Music Control Views Module.
Interactive UI buttons for music playback control.

Note: Type checker warnings for VoiceProtocol/VoiceClient and Interaction
are suppressed because discord.py's type stubs don't fully reflect runtime behavior.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, cast

import discord

if TYPE_CHECKING:
    from .cog import Music


class MusicControlView(discord.ui.View):
    """Interactive music control buttons."""

    def __init__(self, cog: Music, guild_id: int, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = guild_id
        self.message: discord.Message | None = None  # Store message reference for timeout handling

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user is in the same voice channel as the bot."""
        # Verify user is a guild Member (not a DM User)
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟเวอร์", ephemeral=True)
            return False
        # If the bot isn't in a voice channel, controls have nothing to act on.
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message("Bot is not connected to voice", ephemeral=True)
            return False
        member = interaction.user
        if not member.voice:
            await interaction.response.send_message("❌ คุณต้องอยู่ในห้องเสียงก่อน", ephemeral=True)
            return False

        # Check if bot is in voice and user is in the same channel
        if interaction.guild and interaction.guild.voice_client:
            vc = cast(discord.VoiceClient, interaction.guild.voice_client)
            if member.voice.channel != vc.channel:
                await interaction.response.send_message(
                    "❌ คุณต้องอยู่ในห้องเสียงเดียวกับบอท", ephemeral=True
                )
                return False

        return True

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="music_pause")
    async def pause_resume_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Toggle pause/resume."""
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message("❌ บอทไม่ได้เล่นเพลงอยู่", ephemeral=True)
            return

        voice_client = cast(discord.VoiceClient, interaction.guild.voice_client)

        if voice_client.is_paused():
            previous_emoji = button.emoji
            button.emoji = "⏸️"
            try:
                voice_client.resume()
                # Shared bookkeeping (mirrors the text !resume command) so a
                # button-initiated resume advances start_time by the paused
                # interval — otherwise nowplaying/progress drifts past the
                # real audio position. Only on a successful state toggle.
                self.cog.mark_resume(self.guild_id)
            except discord.ClientException as e:
                # Restore the emoji and surface the failure to the user
                button.emoji = previous_emoji
                await interaction.response.send_message(f"❌ ไม่สามารถเล่นต่อได้: {e}", ephemeral=True)
                return
            await interaction.response.edit_message(view=self)
        elif voice_client.is_playing():
            previous_emoji = button.emoji
            button.emoji = "▶️"
            try:
                voice_client.pause()
                # Record the pause instant via the shared helper so resume /
                # fix / nowplaying compute elapsed position correctly.
                self.cog.mark_pause(self.guild_id)
            except discord.ClientException as e:
                button.emoji = previous_emoji
                await interaction.response.send_message(
                    f"❌ ไม่สามารถหยุดชั่วคราวได้: {e}", ephemeral=True
                )
                return
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงให้หยุดชั่วคราว", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Skip current track."""
        if not interaction.guild or not interaction.guild.voice_client:
            await interaction.response.send_message("❌ ไม่มีเพลงให้ข้าม", ephemeral=True)
            return

        voice_client = cast(discord.VoiceClient, interaction.guild.voice_client)
        # Allow skipping a PAUSED track too — calling stop() while paused still
        # fires the after-callback that advances the queue. The text `skip`
        # command already accepts both states; this keeps the button in sync.
        if voice_client.is_playing() or voice_client.is_paused():
            self.cog._gs(self.guild_id).loop = False  # Disable loop
            voice_client.stop()
            await interaction.response.send_message("⏭️ ข้ามเพลง", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงให้ข้าม", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stop playback and clear queue."""
        # Mutate the existing deque in place — assigning a fresh deque
        # would orphan the reference held by play_next(), and the in-flight
        # track callback would keep operating on the abandoned object
        # (treating the queue as still populated).
        gs = self.cog._gs(self.guild_id)
        gs.queue.clear()
        gs.loop = False
        gs.current_track = None

        if interaction.guild and interaction.guild.voice_client:
            voice_client = cast(discord.VoiceClient, interaction.guild.voice_client)
            voice_client.stop()

        await interaction.response.send_message("⏹️ หยุดเล่นและล้างคิวแล้ว", ephemeral=True)

        # Disable all buttons in the view before stopping so the message
        # reflects that the controls are no longer interactive.
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

        self.stop()  # Stop the view

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle loop mode."""
        current_loop = self.cog._gs(self.guild_id).loop
        self.cog._gs(self.guild_id).loop = not current_loop

        button.style = (
            discord.ButtonStyle.success
            if self.cog._gs(self.guild_id).loop
            else discord.ButtonStyle.secondary
        )
        # `edit_message` can raise NotFound (message deleted by user) or
        # HTTPException (permissions changed). If it does, the interaction
        # is no longer acknowledged, so a follow-up `followup.send` would
        # also fail. Catch and bail cleanly.
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            self.cog._gs(self.guild_id).loop = current_loop
            return
        msg = "🔁 เปิดโหมดวนซ้ำ" if self.cog._gs(self.guild_id).loop else "➡️ ปิดโหมดวนซ้ำ"
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.send(msg, ephemeral=True)

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        # Try to edit the message to show disabled buttons
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, AttributeError):
                pass  # Message may have been deleted, inaccessible, or stale ref
