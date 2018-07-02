from collections import deque

from discord.ext import commands

from ..core import AbstractPlayerEventAdapter
from ..core import Lavalink
from ..core import TrackEndEvent, TrackStuckEvent, TrackStartEvent, TrackExceptionEvent, TrackPauseEvent, TrackResumeEvent


class MusicPlayer(AbstractPlayerEventAdapter):
    def __init__(self, link, mpm):
        self.mpm = mpm
        self.stopped = False
        self.link = link
        self.player = link.player
        self.current = None
        self.queue = deque()

        self.player.event_adapter = self

    async def search(self, query):
        return await self.link.get_tracks(query)

    async def add_track(self, track):
        if not self.current:
            await self.player.play(track)
            self.current = track
            return -1
        self.queue.append(track)
        return len(self.queue)-1

    async def skip(self):
        await self.player.stop()

    async def stop(self):
        del self.mpm.music_players[self.link.guild.id]  # dereferencing reeeeee
        await self.link.disconnect()
        await self.player.stop()
        self.stopped = True

    async def track_pause(self, event: TrackPauseEvent):
        pass

    async def track_resume(self, event: TrackResumeEvent):
        pass

    async def track_start(self, event: TrackStartEvent):
        pass

    async def track_end(self, event: TrackEndEvent):
        if self.queue and not self.stopped:
            track = self.queue.popleft()
            await self.player.play(track)
            self.current = track

    async def track_exception(self, event: TrackExceptionEvent):
        pass

    async def track_stuck(self, event: TrackStuckEvent):
        pass


class MusicPlayerManger:
    def __init__(self, lavalink, bot):
        self.lavalink = lavalink
        self.bot = bot
        self.music_players = {}
        self.bot.loop.create_task(
            self.lavalink.add_node("local", "ws://localhost:8080", "http://localhost:2333", "youshallnotpass")
        )

    def get_music_player(self, guild, select_if_absent=False):
        if select_if_absent and guild.id not in self.music_players:
            self.music_players[guild.id] = MusicPlayer(self.lavalink.get_link(guild), self)
        return self.music_players.get(guild.id)


class Music:
    def __init__(self, bot):
        self.bot = bot
        self.mpm = MusicPlayerManger(Lavalink("USER_ID", 1), bot)

    @commands.command()
    async def play(self, ctx, *, query):
        mp = self.mpm.get_music_player(ctx.guild, True)
        tracks = await mp.search(query)
        track = tracks[0]
        await mp.link.connect(ctx.author.voice.channel)
        res = await mp.add_track(track)
        if res == -1:
            await ctx.send(f"Playing `{track.title}` now")
        else:
            await ctx.send(f"Added `{track.title}` to the queue at position: {res+1}")

    @commands.command()
    async def skip(self, ctx):
        mp = self.mpm.get_music_player(ctx.guild, False)
        await mp.skip()
        await ctx.send(f"The current song has been skipped")

    @commands.command()
    async def stop(self, ctx):
        mp = self.mpm.get_music_player(ctx.guild, False)
        await mp.stop()
        await ctx.send(f"The player has been stopped")


def setup(bot):
    bot.add_cog(Music(bot))
