import json

import websockets

from .events import TrackEndEvent, TrackStuckEvent, TrackExceptionEvent


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
    def __init__(self, lavalink, name, uri, headers):
        self.name = name
        self.lavalink = lavalink
        self.uri = uri
        self.headers = headers
        self.available = False
        self.stats = None
        self.ws = None

    async def connect(self):
        with websockets.connect(self.uri, extra_headers=self.headers) as ws:
            self.ws = ws
            await self.on_open()
            self.lavalink.loop.create_task(self.listen())

    async def listen(self):
        try:
            while self.ws.open:
                msg = await self.ws.recv()
                await self.on_message(json.loads(msg))
        except websockets.ConnectionClosed as e:
            await self.on_close(e.code, e.reason)

    async def on_open(self):
        print("Node connected")
        self.available = True
        self.lavalink.load_balancer.on_node_connect(self)

    async def on_close(self, code, reason):
        self.available = False
        if not reason:
            reason = "<no reason given>"

        # we gotta use print for now until someone writes me good logging code
        if code == 1000:
            print(f"Connection to {self.uri} closed gracefully with reason: {reason}")
        else:
            print(f"Connection to {self.uri} closed unexpectedly with code: {code}, reason: {reason}")

        await self.lavalink.load_balancer.on_node_disconnect(self)

    async def on_message(self, msg):
        """NOT DONE"""
        op = msg.get("op")
        if op == "playerUpdate":
            link = self.lavalink.get_link(msg.get("guildId"))
            link.player.provide_state(msg.get("state"))
        elif op == "stats":
            self.stats = NodeStats(msg)
        elif op == "event":
            await self.handle_event(msg)
        else:
            # log this shit
            pass

    async def send(self, msg):
        pass

    async def handle_event(self, msg):
        player = self.lavalink.get_link(msg.get("guildId")).player
        event = None
        event_type = msg.get("type")

        if event_type == "TrackEndEvent":
            event = TrackEndEvent(player, player.track, msg.get("reason"))
        elif event_type == "TrackExceptionEvent":
            event = TrackExceptionEvent(player, player.track, msg.get("error"))
        elif event_type == "TrackStuckEvent":
            event = TrackStuckEvent(player, player.track, msg.get("thresholdMs"))
        else:
            # log this shit pls
            pass

        if event:
            await player.trigger_event(event)
