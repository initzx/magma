from time import time

from .exceptions import IllegalAction
from .events import InternalEventAdapter, TrackPauseEvent, TrackResumeEvent, TrackStartEvent


class AudioTrack:
    def __init__(self, track):
        self.encoded_track = track['track']
        self.stream = track['info']['isStream']
        self.uri = track['info']['uri']
        self.title = track['info']['title']
        self.author = track['info']['author']
        self.identifier = track['info']['identifier']
        self.seekable = track['info']['isSeekable']
        self.duration = track['info']['length']


class Player:
    internal_event_adapter = InternalEventAdapter()

    def __init__(self, link):
        self.link = link
        self.track = None
        self.event_adapter = None
        self.paused = False
        self.volume = 100
        self.update_time = -1
        self._position = -1

    @property
    def position(self):
        if not self.paused:
            diff = time()*1000 - self.update_time
            return min(self._position + diff, self.track.duration)
        return min(self._position, self.track.duration)

    async def seek_to(self, position):
        if not self.track:
            raise IllegalAction("Not playing anything right now")
        if not self.track.seekabble:
            raise IllegalAction("Cannot seek for this track")

        payload = {
            "op": "seek",
            "guildId": self.link.guild.id,
            "position": position
        }

        self.link.get_node(True).send(payload)

    async def set_paused(self, pause):
        if pause == self.paused:
            return

        payload = {
            "op": "pause",
            "guildId": self.link.guild.id,
            "pause": pause,
        }

        self.link.get_node(True).send(payload)
        self.paused = pause

        if pause:
            await self.trigger_event(TrackPauseEvent(self))
        else:
            await self.trigger_event(TrackResumeEvent(self))

    async def set_volume(self, volume):
        if not 0 <= volume <= 150:
            raise IllegalAction("Volume must be between 0-150")

        payload = {
            "op": "volume",
            "guildId": self.link.guild.id,
            "volume": volume,
        }

        self.link.get_node(True).send(payload)
        self.volume = volume

    async def provide_state(self, state):
        self.update_time = state["time"]
        self._position = state["position"]

    async def play(self, track, position=0):
        payload = {
            "op": "play",
            "guildId": self.link.guild.id,
            "track": track.encoded_track,
            "startTime": position,
            "paused": self.paused
        }
        self.link.get_node(True).send(payload)
        self.update_time = time()*1000
        self.track = track
        await self.trigger_event(TrackStartEvent(self, track))

    async def stop(self):
        payload = {
            "op": "stop",
            "guildId": self.link.guild.id,
        }

        self.link.get_node(True).send(payload)

    async def node_changed(self):
        pass

    async def trigger_event(self, event):
        await Player.internal_event_adapter.on_event(event)
        if self.event_adapter:
            await self.event_adapter.on_event(event)
