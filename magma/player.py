from time import time

from .exceptions import IllegalAction
from .events import InternalEventAdapter, TrackPauseEvent, TrackResumeEvent, TrackStartEvent


class AudioTrack:
    """
    The base AudioTrack class that is used by the player to play songs
    """
    def __init__(self, track):
        self.encoded_track = track['track']
        self.stream = track['info']['isStream']
        self.uri = track['info']['uri']
        self.title = track['info']['title']
        self.author = track['info']['author']
        self.identifier = track['info']['identifier']
        self.seekable = track['info']['isSeekable']
        self.duration = track['info']['length']
        self.user_data = None


class Player:
    internal_event_adapter = InternalEventAdapter()

    def __init__(self, link):
        self.link = link
        self.current = None
        self.event_adapter = None
        self.paused = False
        self.volume = 100
        self.update_time = -1
        self._position = -1

    @property
    def is_playing(self):
        return self.current is not None

    @property
    def position(self):
        # We're going to get the position of the current song
        # There is a delay between each update so we gotta do some calculations
        # btw this is in fucking milliseconds
        if not self.paused:
            diff = round(time()*1000) - self.update_time
            return min(self._position + diff, self.current.duration)
        return min(self._position, self.current.duration)

    def reset(self):
        self.current = None
        self.update_time = -1
        self._position = -1

    async def provide_state(self, state):
        self.update_time = state["time"]
        if "position" in state:
            self._position = state["position"]
            return
        self.reset()

    async def seek_to(self, position):
        """
        Sends a request to the Lavalink node to seek to a specific position
        :param position: The position in millis
        :return:
        """
        if not self.current:
            raise IllegalAction("Not playing anything right now")
        if not self.current.seekable:
            raise IllegalAction("Cannot seek for this track")

        payload = {
            "op": "seek",
            "guildId": str(self.link.guild.id),
            "position": position
        }

        node = await self.link.get_node(True)
        await node.send(payload)

    async def set_paused(self, pause):
        """
        Sends a request to the Lavalink node to set the paused state
        :param pause: A boolean that indicates the pause state
        :return:
        """

        payload = {
            "op": "pause",
            "guildId": str(self.link.guild.id),
            "pause": pause,
        }

        node = await self.link.get_node(True)
        await node.send(payload)

        if pause:
            await self.trigger_event(TrackPauseEvent(self))
        else:
            await self.trigger_event(TrackResumeEvent(self))

    async def set_volume(self, volume):
        """
        Sends a request to the Lavalink node to set the volume
        :param volume: An integer from 0-150
        :return:
        """
        if not 0 <= volume <= 150:
            raise IllegalAction("Volume must be between 0-150")

        payload = {
            "op": "volume",
            "guildId": str(self.link.guild.id),
            "volume": volume,
        }

        node = await self.link.get_node(True)
        await node.send(payload)
        self.volume = volume

    async def play(self, track, position=0):
        """
        Sends a request to the Lavalink node to play an AudioTrack
        :param track: The AudioTrack to play
        :param position: Optional; the position to start the song at
        :return:
        """
        payload = {
            "op": "play",
            "guildId": str(self.link.guild.id),
            "track": track.encoded_track,
            "startTime": position,
            "paused": self.paused
        }
        node = await self.link.get_node(True)
        await node.send(payload)
        self.update_time = time()*1000
        self.current = track
        await self.trigger_event(TrackStartEvent(self, track))

    async def stop(self):
        """
        Sends a request to the Lavalink node to stop the current playing song
        :return:
        """
        payload = {
            "op": "stop",
            "guildId": str(self.link.guild.id),
        }

        node = await self.link.get_node(True)
        await node.send(payload)

    async def node_changed(self):
        if self.current:
            await self.play(self.current, self.position)

    async def trigger_event(self, event):
        await Player.internal_event_adapter.on_event(event)
        if self.event_adapter:  # If we defined our on adapter
            await self.event_adapter.on_event(event)
