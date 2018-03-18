from .exceptions import IllegalAction


class LoadBalancer:

    """TODO: add custom penalty support"""

    def __init__(self, lavalink):
        self.lavalink = lavalink

    def determine_best_node(self, guild):
        nodes = self.lavalink.nodes.values()
        best_node = None
        record = 999999999999999
        for node in nodes:
            total = Penalties(node, guild, self.lavalink).total
            if total and total < record:
                best_node = node
                record = total
        if not (best_node or best_node.available):
            raise IllegalAction("No available nodes")
        return best_node

    async def on_node_disconnect(self, node):
        for link in self.lavalink.links.values():
            if node == link.get_node():
                link.change_node()

    async def on_node_connect(self, node):
        for link in self.lavalink.links.values():
            if not link.get_node:
                link.change_node(node)


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
        if not self.node.available or not self.node.stats:
            return 999999999999998
        return self.player_penalty + self.cpu_penalty + self.deficit_frame_penalty + self.null_frame_penalty
