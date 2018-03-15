import websockets


class Node:
    def __init__(self, lavalink, name, uri, headers):
        self.name = name
        self.lavalink = lavalink
        self.uri = uri
        self.headers = headers
        self.ws = None

    async def connect(self):
        try:
            with websockets.connect(self.uri, extra_headers=self.headers) as ws:
                self.ws = ws
                self.lavalink.loop.create_task(self.listen())
        except Exception as e:
            print(e)

    async def listen(self):
        while self.ws.open:
            msg = await self.ws.recv()
            await self.on_message(msg)

    async def on_message(self, msg):
        pass

    async def send(self, msg):
        pass

