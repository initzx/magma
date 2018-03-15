from .player import Player
from .node import Node


class Lavalink:
    def __init__(self, bot):
        self.bot = bot
        self.loop = self.bot.loop
        self.user_id = bot.user.id
        self.shard_count = bot.shard_count
        self.nodes = {}
        self.links = {}

    async def add_node(self, name, uri, password):
        headers = {
            "Authorization": password,
            "Num-Shards": self.shard_count,
            "User-Id": self.user_id
        }

        node = Node(self, name, uri, headers)
        await node.connect()
        self.nodes[name] = node

    def get_link(self, guild_id):
        if not guild_id in self.links:
            self.links[guild_id] = Link(self, guild_id)
        return self.links[guild_id]


class Link:
    def __init__(self, lavalink, guild):
        self.lavalink = lavalink
        self.guild = guild
        self._player = None

    @property
    def player(self):
        if not self._player:
            self._player = Player(self)
        return self._player

    async def connect(self, channel):


    async def disconnect(self):
        pass

