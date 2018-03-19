
class IllegalAction(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class NodeException(Exception):
    def __init__(self, msg):
        super().__init__(msg)
