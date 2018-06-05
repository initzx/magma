# Implementation
```python
class MusicPlayer(AbstractPlayerEventAdapter):
    def __init__(self):
        # business rules
        
    async def track_pause(self, event: TrackPauseEvent):
        pass

    async def track_resume(self, event: TrackResumeEvent):
        pass

    async def track_start(self, event: TrackStartEvent):
        pass

    async def track_end(self, event: TrackEndEvent):
        pass

    async def track_exception(self, event: TrackExceptionEvent):
        pass

    async def track_stuck(self, event: TrackStuckEvent):
        pass
```

### Basic implementation
You should subclass `AbstractPlayerEventAdapter` to handle all business logic and other components related to your bot. I also recommend using a manager that manages your inherited adapters in order to allow more control over the different adapters.

### Advanced implementation
A more advanced implementation can be found in Himebot's code: <br />
[Player manager and player](https://github.com/initzx/rewrite/tree/multiprocessing/audio) <br />
[Commands and such](https://github.com/initzx/rewrite/blob/multiprocessing/commands/music.py) 

### Logging
The handler of Magma's logger is `logging.NullHandler` by default, though you can choose to receive logging messages by doing for example:
```python
import logging
logging.basicConfig(format="%(levelname)s -- %(name)s.%(funcName)s : %(message)s", level=logging.INFO)
```
Place the code above somewhere where you initialize the bot.
