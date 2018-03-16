from .exceptions import IllegalAction


class LoadBalancer:

    """TODO: add custom penalty support"""

    def __init__(self, lavalink):
        self.lavalink = lavalink

    def determine_best_node(self, guild):
        nodes = self.lavalink.nodes.values()
        if not nodes:
            raise IllegalAction("No available nodes")

        best_node = nodes[0]
        record = Penalties(nodes[0], guild, self.lavalink).total
        for node in nodes[1:]:
            total = Penalties(node, guild, self.lavalink).total
            if total < record:
                best_node = node
                record = total

        return best_node

    async def on_node_disconnect(self, node):
        pass

    async def on_node_connect(self, node):
        pass


class Penalties:
    def __init__(self, node, guild, lavalink):
        self.node = node
        self.guild = guild
        self.lavalink = lavalink

        self.player_penalty = 0
        self.cpu_penalty = 0
        self.deficit_frame_penalty = 0
        self.null_frame_penalty = 0

        stats = node.stats
        if not stats:
            return

        if lavalink:
            # reee complexity levels
            for link in lavalink.links().values():
                if node == link.get_node() and link.player.track and not link.player.paused:
                    self.player_penalty += 1
        else:
            self.player_penalty = stats.playing_players

        self.cpu_penalty = 1.05**(100*stats.system_load * 10 - 10)
        if stats.avg_frame_deficit != -1:
            self.deficit_frame_penalty = 1.03**(500 * (stats.avg_frame_deficit/3000) * 600 - 600)
            self.null_frame_penalty = 1.03**(500 * (stats.avg_frame_nulled/3000) * 300 - 300)
            self.null_frame_penalty *= 2

    @property
    def total(self):
        if not (self.node.ws and self.node.ws.open) or not self.node.stats:
            return -1
        return self.player_penalty + self.cpu_penalty + self.deficit_frame_penalty + self.null_frame_penalty
