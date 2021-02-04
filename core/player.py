import traceback
from enum import Enum
from time import time

from .exceptions import IllegalAction
from .events import InternalEventAdapter, TrackPauseEvent, TrackResumeEvent, TrackStartEvent


class LoadTypes(Enum):
    NO_MATCHES = -2
    LOAD_FAILED = -1
    UNKNOWN = 0
    TRACK_LOADED = 1
    PLAYLIST_LOADED = 2
    SEARCH_RESULT = 3


class BassModes(Enum):
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"
    SICKO = "SICKO"


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


class AudioTrackPlaylist:
    def __init__(self, results):
        try:
            self.playlist_info = results["playlistInfo"]
            self.playlist_name = self.playlist_info.get("name")
            self.selected_track = self.playlist_info.get("selectedTrack")
            self.load_type = LoadTypes[results["loadType"]]
            self.tracks = [AudioTrack(track) for track in results["tracks"]]
        except KeyError:
            raise IllegalAction(f"Results invalid!, received: {results}")

    @property
    def is_playlist(self):
        return self.load_type.value == 2 and self.__len__() > 1

    @property
    def is_empty(self):
        return self.load_type.value < 0 or self.__len__() == 0

    def __iter__(self):
        for track in self.tracks:
            yield track

    def __len__(self):
        return self.tracks.__len__()

    def __getitem__(self, item):
        return self.tracks[item]


class Equalizer:
    def __init__(self, options):
        self.__slots__ = tuple(mode.value for mode in options.keys())
        for k, v in options.items():
            setattr(self, k.value, v)

    @classmethod
    def bassboost(cls):
        return cls(
            {
                BassModes.OFF: [(0, 0), (1, 0)],
                BassModes.LOW: [(0, 0.25), (1, 0.15)],
                BassModes.MEDIUM: [(0, 0.50), (1, 0.25)],
                BassModes.HIGH: [(0, 0.75), (1, 0.50)],
                BassModes.EXTREME: [(0, 1), (1, 0.75)],
                BassModes.SICKO: [(0, 1), (1, 1)],
            }
        )


class Player:
    internal_event_adapter = InternalEventAdapter()

    def __init__(self, link):
        self.link = link
        self.current = None
        self.event_adapter = None
        self.paused = False
        self.volume = 100
        self.equalizer = {band: 0 for band in range(15)}
        self.bass_mode = BassModes.OFF
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
            diff = round((time()-self.update_time)*1000)
            return min(self._position + diff, self.current.duration)
        return min(self._position, self.current.duration)

    def reset(self):
        self.current = None
        self.update_time = -1
        self._position = -1

    async def provide_state(self, state):
        self.update_time = time()
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
            "guildId": str(self.link.guild_id),
            "position": position
        }

        node = await self.link.get_node()
        await node.send(payload)

    async def set_paused(self, pause):
        """
        Sends a request to the Lavalink node to set the paused state
        :param pause: A boolean that indicates the pause state
        :return:
        """

        payload = {
            "op": "pause",
            "guildId": str(self.link.guild_id),
            "pause": pause,
        }

        node = await self.link.get_node()
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
            "guildId": str(self.link.guild_id),
            "volume": volume,
        }

        node = await self.link.get_node()
        await node.send(payload)
        self.volume = volume

    async def set_eq(self, gains_list):
        """
        Sets gain for multiple bands
        :param gains_list: a list of tuples in (band, gain) order.
        :return:
        """
        bands = []
        for band, gain in gains_list:

            if not -1 < band < 15:
                continue

            gain = max(min(float(gain), 1.0), -0.25)
            bands.append({"band": band, "gain": gain})
            self.equalizer[band] = gain

        payload = {
            "op": "equalizer",
            "guildId": str(self.link.guild_id),
            "bands": bands
        }

        node = await self.link.get_node()
        await node.send(payload)

    async def set_gain(self, band, gain):
        """
        Sets the gain for 1 band
        :param band: a band from 0 to 14
        :param gain: a value from -0.25 to 1
        :return:
        """
        await self.set_eq((band, gain))

    async def set_bass(self, bass_mode):
        """
        Sets which bass mode the player is in
        :param bass_mode: an BassModes enum value
        :return:
        """
        gains = Equalizer.bassboost().__dict__[bass_mode.value]
        self.bass_mode = bass_mode
        await self.set_eq(gains)

    async def play(self, track, position=0, no_replace=True):
        """
        Sends a request to the Lavalink node to play an AudioTrack
        :param track: The AudioTrack to play
        :param position: Optional; the position to start the song at
        :param no_replace: if the current track should NOT be replaced
        :return:
        """
        payload = {
            "op": "play",
            "guildId": str(self.link.guild_id),
            "track": track.encoded_track,
            "startTime": position,
            "noReplace": no_replace
        }
        node = await self.link.get_node(True)
        await node.send(payload)
        self.update_time = time()*1000
        self.current = track
        # await self.trigger_event(TrackStartEvent(self, track))

    async def stop(self):
        """
        Sends a request to the Lavalink node to stop the current playing song
        :return:
        """
        payload = {
            "op": "stop",
            "guildId": str(self.link.guild_id),
        }

        node = await self.link.get_node()
        await node.send(payload)

    async def destroy(self):
        """
        Sends a request to the Lavalink node to destroy the player and reset
        :return:
        """
        payload = {
            "op": "destroy",
            "guildId": str(self.link.guild_id),
        }
        node = await self.link.get_node()
        if node and node.connected:
            await node.send(payload)

        if self.event_adapter:
            await self.event_adapter.destroy()
            self.event_adapter = None

    async def node_changed(self):
        if self.current:
            await self.play(self.current, self._position)

            if self.paused:
                await self.set_paused(True)

        if self.volume != 100:
            await self.set_volume(self.volume)

    async def trigger_event(self, event):
        await Player.internal_event_adapter.on_event(event)
        if self.event_adapter:  # If we defined our on adapter
            try:
                await self.event_adapter.on_event(event)
            except:
                traceback.print_exc()
