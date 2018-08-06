import asyncio
import logging
import time
from enum import Enum

from discord import InvalidArgument
from discord.ext.commands import BotMissingPermissions

from .exceptions import IllegalAction
from .load_balancing import LoadBalancer
from .node import Node
from .player import Player, AudioTrackPlaylist

logger = logging.getLogger("magma")


class State(Enum):
    # States the Link can be in
    NOT_CONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    DISCONNECTING = 3
    DESTROYING = 4
    DESTROYED = 5


class Lavalink:
    def __init__(self, user_id, shard_count):

        self.user_id = user_id
        self.shard_count = shard_count
        self.loop = asyncio.get_event_loop()
        self.load_balancer = LoadBalancer(self)
        self.nodes = {}
        self.links = {}

    @property
    def playing_guilds(self):
        return {name: node.stats.playing_players for name, node in self.nodes.items() if node.stats}

    @property
    def total_playing_guilds(self):
        return sum(self.playing_guilds.values())

    async def on_socket_response(self, data):
        """
        YOU MUST ADD THIS WITH `bot.add_listener(lavalink.on_socket_response)`
        """

        if not data.get("t") in ("VOICE_SERVER_UPDATE", "VOICE_STATE_UPDATE"):
            return
        link = self.links.get(int(data['d']['guild_id']))
        if link:
            await link.update_voice(data)

    def get_link(self, guild_id: int, bot=None):
        """
        Return a Link for the specified guild
        :param guild_id: The guild id for the Link
        :param bot: The bot/shard where this was invoked
        :return: A Link
        """
        guild_id = int(guild_id)

        if guild_id in self.links or not bot:
            return self.links.get(guild_id)

        self.links[guild_id] = Link(self, guild_id, bot)
        return self.links[guild_id]

    async def add_node(self, name, uri, rest_uri, password):
        """
        Add a Lavalink node

        :param name: The name of the node
        :param uri: The web socket URI of the node, ("ws://localhost:80")
        :param rest_uri: The REST URI of the node, ("http://localhost:2333")
        :param password: The password to connect to the node
        :return: A node
        """
        headers = {
            "Authorization": password,
            "Num-Shards": self.shard_count,
            "User-Id": self.user_id
        }

        node = Node(self, name, uri, rest_uri, headers)
        await node.connect()
        self.nodes[name] = node

    async def get_best_node(self):
        """
        Determines the best Node based on penalty calculations

        :return: A Node
        """
        return await self.load_balancer.determine_best_node()


class Link:
    def __init__(self, lavalink, guild_id, bot):
        self.lavalink = lavalink
        self.guild_id = guild_id
        self.bot = bot
        self.state = State.NOT_CONNECTED
        self.last_voice_update = {}
        self.last_session_id = None
        self._player = None
        self.node = None

    @property
    def player(self):
        if not self._player:
            self._player = Player(self)
        return self._player

    def set_state(self, state):
        if self.state.value > 3 and state.value != 5:
            raise IllegalAction(f"Cannot change the state to {state} when the state is {self.state}")
        self.state = state

    async def update_voice(self, data):
        logger.debug(f"Received voice update data: {data}")
        if not self.guild_id:  # is this even necessary? :thinking:
            raise IllegalAction("Attempted to start audio connection with a guild that doesn't exist")

        if data["t"] == "VOICE_SERVER_UPDATE":
            self.last_voice_update.update({
                "op": "voiceUpdate",
                "event": data["d"],
                "guildId": data["d"]["guild_id"],
                "sessionId": self.last_session_id
            })
            node = await self.get_node(True)
            await node.send(self.last_voice_update)
            self.set_state(State.CONNECTED)
        else:  # data["t"] == "VOICE_STATE_UPDATE"

            # We're selfish and only care about ourselves
            if int(data["d"]["user_id"]) != self.bot.user.id:
                return

            channel_id = data["d"]["channel_id"]
            self.last_session_id = data["d"]["session_id"]
            if not channel_id and self.state != State.DESTROYED:
                self.state = State.NOT_CONNECTED
                if self.node:
                    payload = {
                        "op": "destroy",
                        "guildId": data["d"]["guild_id"]
                    }
                    await self.node.send(payload)

    async def get_tracks(self, query):
        """
        Get a list of AudioTracks from a query

        :param query: The query to pass to the Node
        :return:
        """
        node = await self.get_node(True)
        results = await node.get_tracks(query)
        return AudioTrackPlaylist(results)

    async def get_tracks_yt(self, query):
        return await self.get_tracks("ytsearch:" + query)

    async def get_tracks_sc(self, query):
        return await self.get_tracks("scsearch:" + query)

    async def get_node(self, select_if_absent=False):
        """
        Gets a Node for the link

        :param select_if_absent: A boolean that indicates if a Node should be created if there is none
        :return: A Node
        """
        if select_if_absent and not (self.node and self.node.available):
            await self.change_node(await self.lavalink.get_best_node())
        return self.node

    async def change_node(self, node):
        """
        Change to another node

        :param node: The Node to change to
        :return:
        """
        self.node = node
        self.node.links[self.guild_id] = self
        if self.last_voice_update:
            await node.send(self.last_voice_update)
        if self._player:
            await self._player.node_changed()
    
    async def connect(self, channel):
        """
        Connect to a voice channel

        :param channel: The voice channel to connect to
        :return:
        """
        # We're using discord's websocket, not lavalink
        if channel.guild.id != self.guild_id:
            raise InvalidArgument("The guild of the channel isn't the the same as the link's!")
        if channel.guild.unavailable:
            raise IllegalAction("Cannot connect to guild that is unavailable!")

        me = channel.guild.me
        permissions = me.permissions_in(channel)
        if (not permissions.connect or len(channel.members) >= channel.user_limit >= 1) and not permissions.move_members:
            raise BotMissingPermissions(["connect"])

        self.set_state(State.CONNECTING)
        payload = {
            "op": 4,
            "d": {
                "guild_id": self.guild_id,
                "channel_id": str(channel.id),
                "self_mute": False,
                "self_deaf": False
            }
        }
        await self.bot._connection._get_websocket(self.guild_id).send_as_json(payload)

        start = time.monotonic()
        while not (me.voice and me.voice.channel):
            await asyncio.sleep(0.1)
            if start-time.monotonic() >= 10:
                raise IllegalAction("Couldn't connect to the channel within a reasonable timeframe!")

    async def disconnect(self):
        """
        Disconnect from the current voice channel

        :return:
        """
        # We're using discord's websocket, no lavalink
        payload = {
            "op": 4,
            "d": {
                "guild_id": self.guild_id,
                "channel_id": None,
                "self_mute": False,
                "self_deaf": False
            }
        }

        self.set_state(State.DISCONNECTING)
        await self.bot._connection._get_websocket(self.guild_id).send_as_json(payload)

    async def destroy(self):
        self.lavalink.links.pop(self.guild_id)
        if self._player and self.node:
            self.node.links.pop(self.guild_id)
            await self._player.destroy()
            self._player = None

