import json

import asyncio
import threading
from collections import deque

import aiohttp
import logging
import websockets
from discord.backoff import ExponentialBackoff

from .events import TrackEndEvent, TrackStuckEvent, TrackExceptionEvent, TrackStartEvent
from .exceptions import NodeException

logger = logging.getLogger("magma")


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


class ListenerThread(threading.Thread):
    def __init__(self, node, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = f"{node.name}-Listener"
        self.daemon = True
        self.node = node
        self.ws = node.ws
        self.loop = node.ws.loop
        self._stop_ev = threading.Event()

    def run(self):
        try:
            while not self._stop_ev.isSet():
                future = asyncio.run_coroutine_threadsafe(self.node.poll(), loop=self.loop)
                res = future.result()
        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection to `{self.node.name}` was closed`! Reason: {e.code}, {e.reason}")
            self.node.available = False
            if self.node.closing:
                asyncio.run_coroutine_threadsafe(self.node.on_close(e.code, e.reason), loop=self.loop)
                return

            logger.info(f"Attempting to reconnect `{self.node.name}`")
            future = asyncio.run_coroutine_threadsafe(self.node.connect(), loop=self.loop)
            future.result()

    def stop(self):
        self._stop_ev.set()


class Node:
    def __init__(self, lavalink, name, host, port, headers):
        self.name = name
        self.lavalink = lavalink
        self.links = {}
        self.headers = headers
        self.keep_alive = None
        self.stats = None
        self.ws = None
        self.send_queue = asyncio.Queue()
        self.listener_thread = None
        self.available = False
        self.closing = False

        self.uri = f"ws://{host}:{port}"
        self.rest_uri = f"http://{host}:{port}"

    async def _connect(self):
        backoff = ExponentialBackoff(2)
        while not (self.ws and self.ws.open):
            try:
                self.ws = await websockets.client.connect(self.uri,
                                                          ping_interval=5,
                                                          max_size=None,
                                                          max_queue=None,
                                                          extra_headers=self.headers)
                asyncio.create_task(self.poll())
                asyncio.create_task(self._send_task())
                # self.listener_thread = ListenerThread(self)
                # self.listener_thread.start()
            except OSError:
                delay = backoff.delay()
                logger.error(f"Connection refused, trying again in {delay:.2f}s")
                await asyncio.sleep(delay)

    async def connect(self):
        await self._connect()
        await self.on_open()

    async def disconnect(self):
        logger.info(f"Closing websocket connection for node: {self.name}")
        self.closing = True
        await self.ws.close()

    async def _keep_alive(self):
        """
        **THIS IS VERY IMPORTANT**

        Lavalink will sometimes fail to recognize the client connection if
        a ping is not sent frequently. Websockets sends by default, a ping
        every 5-6 seconds, but this is not enough to maintain the connection.

        This is likely due to the deprecated ws draft: RFC 6455
        """
        try:
            while True:
                await self.ws.ping()
                await asyncio.sleep(2)
        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection to `{self.name}` was closed! Reason: {e.code}, {e.reason}")
            self.available = False
            if self.closing:
                await self.on_close(e.code, e.reason)
                return

            try:
                logger.info(f"Attempting to reconnect `{self.name}`")
                await self.connect()
            except NodeException:
                await self.on_close(e.code, e.reason)

    async def poll(self):
        try:
            while True:
                msg = await self.ws.recv()
                logger.debug(f"Received websocket message from `{self.name}`: {msg}")
                await self.on_message(json.loads(msg))
        except websockets.ConnectionClosed:
            logger.info(f"Connection closed to `{self.name}`")

    async def _send_task(self):
        while True:
            msg = await self.send_queue.get()
            logger.debug(f"Sending websocket message: {msg}")
            await self.ws.send(json.dumps(msg))

    async def send(self, msg):
        if not self.ws or not self.ws.open:
            self.available = False
            raise NodeException("Websocket is not ready, cannot send message")
        # logger.debug(f"Sending websocket message: {msg}")
        # await self.ws.send(json.dumps(msg))
        await self.send_queue.put(msg)

    async def on_open(self):
        self.available = True
        await self.lavalink.load_balancer.on_node_connect(self)

    async def on_close(self, code=None, reason=None):
        self.closing = False
        if self.keep_alive:
            self.keep_alive.stop()

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
            if link:
                await link.player.provide_state(msg.get("state"))
        elif op == "stats":
            self.stats = NodeStats(msg)
        elif op == "event":
            await self.handle_event(msg)
        else:
            logger.info(f"Received unknown op: {op}")

    async def get_tracks(self, query):
        # Fetch tracks from the Lavalink node using its REST API
        params = {"identifier": query}
        headers = {"Authorization": self.headers["Authorization"]}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(self.rest_uri + "/loadtracks", params=params) as resp:
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
