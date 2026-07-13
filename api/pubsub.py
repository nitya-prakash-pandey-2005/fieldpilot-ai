import asyncio

# Simple in-memory pub/sub for SSE streams
class EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, channel: str) -> asyncio.Queue:
        if channel not in self.subscribers:
            self.subscribers[channel] = []
        q = asyncio.Queue()
        self.subscribers[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue):
        if channel in self.subscribers and q in self.subscribers[channel]:
            self.subscribers[channel].remove(q)

    async def publish(self, channel: str, message: dict):
        if channel in self.subscribers:
            for q in self.subscribers[channel]:
                await q.put(message)

bus = EventBus()
