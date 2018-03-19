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

You should subclass `AbstractPlayerEventAdapter` to handle all business logic and other components related to your bot.  
I will also recommend a manager that manages your inherited adapters to allow more control over the different adapters.

