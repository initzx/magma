import logging

from .exceptions import IllegalAction

logger = logging.getLogger("magma")


class LoadBalancer:

    """
    The load balancer is copied from Fre_d's Java client, and works in somewhat the same way
    """

    def __init__(self, lavalink):
        self.lavalink = lavalink

    async def determine_best_node(self):
        nodes = self.lavalink.nodes.values()
        best_node = None
        record = 9e30
        for node in nodes:
            penalties = Penalties(node, self.lavalink)
            total = await penalties.get_total()
            if total and total < record:
                best_node = node
                record = total
        if not best_node or not best_node.available:
            raise IllegalAction("No available nodes")
        return best_node

    async def on_node_disconnect(self, node):
        logger.info(f"Node disconnected: {node.name}")
        for link in self.lavalink.links.values():
            if node == await link.get_node():
                new_node = await self.determine_best_node()
                await link.change_node(new_node)

    async def on_node_connect(self, node):
        logger.info(f"Node connected: {node.name}")
        for link in self.lavalink.links.values():
            if not await link.get_node():
                await link.change_node(node)


class Penalties:
    def __init__(self, node, lavalink):
        self.node = node
        self.lavalink = lavalink

        self.player_penalty = 0
        self.cpu_penalty = 0
        self.deficit_frame_penalty = 0
        self.null_frame_penalty = 0

    async def get_total(self):
        # hard maths
        stats = self.node.stats
        if not stats:
            return

        if self.lavalink:
            # REEEEE complexity levels
            for link in self.lavalink.links.values():
                if self.node == await link.get_node() and link.player.current and not link.player.paused:
                    self.player_penalty += 1
        else:
            self.player_penalty = stats.playing_players

        self.cpu_penalty = 1.05 ** (100 * stats.system_load) * 10 - 10
        if stats.avg_frame_deficit != -1:
            self.deficit_frame_penalty = (1.03 ** (500 * (stats.avg_frame_deficit / 3000))) * 600 - 600
            self.null_frame_penalty = (1.03 ** (500 * (stats.avg_frame_nulled / 3000))) * 300 - 300
            self.null_frame_penalty *= 2

        if not self.node.available or not self.node.stats:
            return 9e30
        return self.player_penalty + self.cpu_penalty + self.deficit_frame_penalty + self.null_frame_penalty
