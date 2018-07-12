import logging

logger = logging.getLogger("magma")
logger.addHandler(logging.NullHandler())

from .events import *
from .exceptions import *
from .lavalink import *
from .player import *
from .miscellaneous import *
from .node import *

