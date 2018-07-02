import asyncio
import json
import logging

import aiohttp
from aiohttp import ClientConnectorError

from .events import TrackEndEvent, TrackStuckEvent, TrackExceptionEvent
from .exceptions import NodeException

logger = logging.getLogger("magma")
timeout = 5
tries = 5


class NodeStats:
    def __init__(self, msg):
        self.msg = msg

        self.players = msg.get("players")
        self.playing_players = msg.get("playingPlayers")
        self.uptime = msg.get("uptime")

        mem = msg.get("memory")
        self.mem_free = mem.get("free")
        self.mem_used = mem.get("used")
        self.mem_allocated = mem.get("allocated")
        self.mem_reservable = mem.get("reserveable")

        cpu = msg.get("cpu")
        self.cpu_cores = cpu.get("cores")
        self.system_load = cpu.get("systemLoad")
        self.lavalink_load = cpu.get("lavalinkLoad")

        frames = msg.get("frameStats")
        if frames:
            # These are per minute
            self.avg_frame_sent = frames.get("sent")
            self.avg_frame_nulled = frames.get("nulled")
            self.avg_frame_deficit = frames.get("deficit")
        else:
            self.avg_frame_sent = -1
            self.avg_frame_nulled = -1
            self.avg_frame_deficit = -1


class Node:
    def __init__(self, lavalink, name, uri, rest_uri, headers):
        self.name = name
        self.lavalink = lavalink
        self.links = {}
        self.uri = uri
        self.rest_uri = rest_uri
        self.headers = headers
        self.ws_client_session = None
        self.ws = None
        self.stats = None
        self.available = False
        self.closing = False

    async def _connect(self, try_=0):
        if not self.ws_client_session:
            self.ws_client_session = aiohttp.ClientSession()

        try:
            self.ws = await self.ws_client_session.ws_connect(self.uri, headers=self.headers)
        except ClientConnectorError:
            if try_ < tries:
                logger.error(f"Connection refused, trying again in {timeout}s, try: {try_+1}/{tries}")
                await asyncio.sleep(timeout)
                await self._connect(try_+1)
            else:
                raise NodeException(f"Connection failed after {tries} tries")

    async def connect(self):
        await self._connect()
        await self.on_open()
        asyncio.ensure_future(self.listen())

    async def disconnect(self):
        logger.info(f"Closing websocket connection for node: {self.name}")
        self.closing = True
        await self.ws.close(message=f"Closing websocket connection for node: {self.name}")

    async def listen(self):
        while True:
            msg = await self.ws.receive()
            logger.debug(f"Received websocket message from `{self.name}`: {msg.data}")
            if msg.type == aiohttp.WSMsgType.text:
                await self.on_message(json.loads(msg.data))
            elif msg.type == aiohttp.WSMsgType.close:
                logger.warning(f"Connection to `{self.name}` was closed! Reason: {msg.data}, {msg.extra}")
                self.available = False

                try:
                    logger.info(f"Attempting to reconnect `{self.name}`")
                    await self.connect()
                except NodeException:
                    await self.on_close(msg.data, msg.extra)
                return
            elif msg.type in (aiohttp.WSMsgType.closing, aiohttp.WSMsgType.closed):
                return

    async def on_open(self):
        await self.lavalink.load_balancer.on_node_connect(self)
        self.available = True

    async def on_close(self, code, reason):
        self.closing = False
        if not reason:
            reason = "<no reason given>"

        if code == 1000:
            logger.info(f"Connection to {self.name} closed gracefully with reason: {reason}")
        else:
            logger.warning(f"Connection to {self.name} closed unexpectedly with code: {code}, reason: {reason}")

        await self.lavalink.load_balancer.on_node_disconnect(self)

    async def on_message(self, msg):
        # We receive Lavalink responses here
        op = msg.get("op")
        if op == "playerUpdate":
            link = self.lavalink.get_link(msg.get("guildId"))
            await link.player.provide_state(msg.get("state"))
        elif op == "stats":
            self.stats = NodeStats(msg)
        elif op == "event":
            await self.handle_event(msg)
        else:
            logger.info(f"Received unknown op: {op}")

    async def send(self, msg):
        logger.debug(f"Sending websocket message: `{msg}`")
        if not self.ws or self.ws.closed:
            self.available = False
            raise NodeException("Websocket is not ready, cannot send message")
        await self.ws.send_json(msg)

    async def get_tracks(self, query):
        # Fetch tracks from the Lavalink node using its REST API
        params = {"identifier": query}
        headers = {"Authorization": self.headers["Authorization"]}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.rest_uri+"/loadtracks", params=params) as resp:
                return await resp.json()

    async def handle_event(self, msg):
        # Lavalink sends us track end event types
        link = self.lavalink.get_link(msg.get("guildId"))
        if not link:
            return  # the link got destroyed

        player = link.player
        event = None
        event_type = msg.get("type")

        if event_type == "TrackEndEvent":
            event = TrackEndEvent(player, player.current, msg.get("reason"))
        elif event_type == "TrackExceptionEvent":
            event = TrackExceptionEvent(player, player.current, msg.get("error"))
        elif event_type == "TrackStuckEvent":
            event = TrackStuckEvent(player, player.current, msg.get("thresholdMs"))
        elif event_type:
            logger.info(f"Received unknown event: {event}")

        if event:
            await player.trigger_event(event)
