# PARTS OF THIS CODE IS TAKEN FROM: https://github.com/Devoxin/Lavalink.py/blob/master/lavalink/websocket.py
# MIT License
#
# Copyright (c) 2019 Luke & William
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import asyncio
import logging
import traceback

import aiohttp
from discord.backoff import ExponentialBackoff

from . import IllegalAction
from .events import TrackEndEvent, TrackStuckEvent, TrackExceptionEvent, TrackStartEvent

logger = logging.getLogger("magma")
logging.getLogger('aiohttp').setLevel(logging.DEBUG)


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
    def __init__(self, lavalink, name, host, port, headers):
        self.name = name
        self.lavalink = lavalink
        self.links = {}
        self.headers = {str(k): str(v) for k, v in headers.items()}
        self.stats = None
        self.session = aiohttp.ClientSession(headers={"Authorization": self.headers["Authorization"]})
        self.ws = None
        self.listen_task = None
        # self.available = False
        self.closing = False

        self.uri = f"ws://{host}:{port}"
        self.rest_uri = f"http://{host}:{port}"

    @property
    def connected(self):
        return self.ws and not self.ws.closed

    async def _connect(self):
        backoff = ExponentialBackoff(5, integral=True)
        while not self.connected:
            try:
                logger.info(f'Attempting to establish websocket connection to {self.name}')
                self.ws = await self.session.ws_connect(self.uri, headers=self.headers)
            except aiohttp.ClientConnectorError:
                logger.warning(f'[{self.name}] Invalid response received; this may indicate that '
                               'Lavalink is not running, or is running on a port different '
                               'to the one you passed to `add_node`.')
            except aiohttp.WSServerHandshakeError as ce:
                if ce.status in (401, 403):
                    logger.error(f'Authentication failed when establishing a connection to {self.name}')
                    return

                logger.warning(f'{self.name} returned a code {ce.status} which was unexpected')

            else:
                logger.info(f'Connection established to {self.name}')
                self.listen_task = asyncio.create_task(self.listen())
                return

            delay = backoff.delay()
            logger.error(f"Connection refused, trying again in {delay}s")
            await asyncio.sleep(delay)

    async def connect(self):
        await self._connect()
        await self.on_open()

    async def disconnect(self):
        logger.info(f"Closing websocket connection for node: {self.name}")
        await self.ws.close()

    async def listen(self):
        async for msg in self.ws:
            logger.debug(f"Received websocket message from `{self.name}`: {msg.data}")
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self.on_message(msg.json())
            elif msg.type == aiohttp.WSMsgType.ERROR:
                exc = self.ws.exception()
                logger.error(f'Received an error from `{self.name}`: {exc}')
                await self.on_close(reason=exc)
                return
            elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                 aiohttp.WSMsgType.CLOSING,
                                 aiohttp.WSMsgType.CLOSED):
                logger.info(f'Received close frame from `{self.name}`: {msg.data}')
                await self.on_close(msg.data, msg.extra)
                return
        await self.on_close(connect_again=True)

    async def send(self, msg):
        if not self.connected:
            await self.on_close(connect_again=True)
        # raise NodeException("Websocket is not ready, cannot send message")

        logger.debug(f"Sending websocket message: {msg}")
        await self.ws.send_json(msg)

    async def get_tracks(self, query, tries=5, retry_on_failure=True):
        # Fetch tracks from the Lavalink node using its REST API
        params = {"identifier": query}
        backoff = ExponentialBackoff(base=1)
        for attempt in range(tries):
            async with self.session.get(self.rest_uri + "/loadtracks", params=params) as resp:
                if resp.status != 200 and retry_on_failure:
                    retry = backoff.delay()
                    logger.error(f"Received status code ({resp.status}) while retrieving tracks, retrying in {retry} seconds. Attempt {attempt+1}/{tries}")
                    continue
                elif resp.status != 200 and not retry_on_failure:
                    logger.error(f"Received status code ({resp.status}) while retrieving tracks, not retrying.")
                    return {}
                res = await resp.json()
                return res

    async def on_open(self):
        await self.lavalink.load_balancer.on_node_connect(self)

    async def on_close(self, code=None, reason=None, connect_again=False):
        self.closing = False

        if not reason:
            reason = "<no reason given>"

        if code == 1000:
            logger.info(f"Connection to {self.name} closed gracefully with reason: {reason}")
        else:
            logger.warning(f"Connection to {self.name} closed unexpectedly with code: {code}, reason: {reason}")

        try:
            await self.lavalink.load_balancer.on_node_disconnect(self)
        except IllegalAction:
            traceback.print_exc()

        if connect_again:
            logger.info(f"Attempting to reconnect to {self.name}...")
            await self.connect()

    async def on_message(self, msg):
        # We receive Lavalink responses here
        op = msg.get("op")
        if op == "playerUpdate":
            link = self.lavalink.get_link(msg.get("guildId"))
            if link:
                await link.player.provide_state(msg.get("state"))
        elif op == "stats":
            self.stats = NodeStats(msg)
        elif op == "event":
            await self.handle_event(msg)
        else:
            logger.info(f"Received unknown op: {op}")

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
        elif event_type == "TrackStartEvent":
            event = TrackStartEvent(player, player.current)
        elif event_type == "TrackExceptionEvent":
            event = TrackExceptionEvent(player, player.current, msg.get("error"))
        elif event_type == "TrackStuckEvent":
            event = TrackStuckEvent(player, player.current, msg.get("thresholdMs"))
        elif event_type == "WebSocketClosedEvent":
            if msg.get("code") == 4006 and msg.get("byRemote"):
                await link.destroy()

        elif event_type:
            logger.info(f"Received unknown event: {event_type}")

        if event:
            await player.trigger_event(event)
