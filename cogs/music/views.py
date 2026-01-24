"""
Music Control Views Module.
Interactive UI buttons for music playback control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .cog import Music


class MusicControlView(discord.ui.View):
    """Interactive music control buttons."""

    def __init__(self, cog: Music, guild_id: int, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = guild_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user is in the same voice channel."""
        if not interaction.user.voice:
            await interaction.response.send_message("❌ คุณต้องอยู่ในห้องเสียงก่อน", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, custom_id="music_pause")
    async def pause_resume_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Toggle pause/resume."""
        voice_client = interaction.guild.voice_client
        if not voice_client:
            await interaction.response.send_message("❌ บอทไม่ได้เล่นเพลงอยู่", ephemeral=True)
            return

        if voice_client.is_paused():
            voice_client.resume()
            button.emoji = "⏸️"
            await interaction.response.edit_message(view=self)
        elif voice_client.is_playing():
            voice_client.pause()
            button.emoji = "▶️"
            await interaction.response.edit_message(view=self)
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงให้หยุดชั่วคราว", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.primary, custom_id="music_skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Skip current track."""
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            self.cog.loops[self.guild_id] = False  # Disable loop
            voice_client.stop()
            await interaction.response.send_message("⏭️ ข้ามเพลง", ephemeral=True)
        else:
            await interaction.response.send_message("❌ ไม่มีเพลงให้ข้าม", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music_stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Stop playback and clear queue."""
        self.cog.queues[self.guild_id] = []
        self.cog.loops[self.guild_id] = False
        self.cog.current_track.pop(self.guild_id, None)

        voice_client = interaction.guild.voice_client
        if voice_client:
            voice_client.stop()

        await interaction.response.send_message("⏹️ หยุดเล่นและล้างคิวแล้ว", ephemeral=True)
        self.stop()  # Stop the view

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music_loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Toggle loop mode."""
        current_loop = self.cog.loops.get(self.guild_id, False)
        self.cog.loops[self.guild_id] = not current_loop

        if self.cog.loops[self.guild_id]:
            button.style = discord.ButtonStyle.success
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("🔁 เปิดโหมดวนซ้ำ", ephemeral=True)
        else:
            button.style = discord.ButtonStyle.secondary
            await interaction.response.edit_message(view=self)
            await interaction.followup.send("➡️ ปิดโหมดวนซ้ำ", ephemeral=True)

    async def on_timeout(self):
        """Disable buttons on timeout."""
        for child in self.children:
            child.disabled = True
        # Try to edit the message to show disabled buttons
        if hasattr(self, 'message') and self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass  # Message may have been deleted or inaccessible
