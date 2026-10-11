"""Share pending work within one event loop / API replica."""
import asyncio


class SingleFlight:
    def __init__(self):
        self._tasks = {}
        self._lock = asyncio.Lock()

    async def join(self, key, factory):
        async with self._lock:
            task = self._tasks.get(key)
            if task is not None:
                return task, False

            async def run():
                try:
                    return await factory()
                finally:
                    async with self._lock:
                        self._tasks.pop(key, None)

            task = asyncio.create_task(run())
            self._tasks[key] = task
            # Observe failures even if every HTTP waiter has disconnected.
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            return task, True

    async def close(self):
        await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
