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
You should subclass `AbstractPlayerEventAdapter` to handle all business logic and other components related to your bot. I will also recommend a manager that manages your inherited adapters to allow more control over the different adapters.

### Logging
The handler of Magma's logger is `logging.NullHandler` by default, though you can choose to receive logging messages by doing for example:
```python
import logging
logging.basicConfig(format="%(levelname)s -- %(name)s.%(funcName)s : %(message)s", level=logging.INFO)
```
Place the code above somewhere where you initialize the bot.
