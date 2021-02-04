
class LavalinkException(Exception):
    def __init__(self, msg):
        self.msg = msg


class IllegalAction(LavalinkException):
    pass


class NodeException(LavalinkException):
    pass
