import logging

logger = logging.getLogger("magma")
logger.addHandler(logging.NullHandler())

from .node import *
from .events import *
from .exceptions import *
from .lavalink import *
from .player import *
from .miscellaneous import *
