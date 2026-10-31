"""Cancellation-safe calls into a disk worker: join before releasing resources."""
import asyncio


def ensure_thread_executor():
    """Resolve the canonical executor before asyncio accesses the public export.

    Python 3.15 can leave concurrent.futures.ThreadPoolExecutor as a lazy
    import object. Importing from its defining module avoids exporting that
    proxy back into concurrent.futures. This also works before protective.py
    has ever been imported, as required by standalone recovery callers.
    """
    import concurrent.futures as futures
    if not isinstance(vars(futures).get("ThreadPoolExecutor"), type):
        from concurrent.futures.thread import ThreadPoolExecutor
        futures.ThreadPoolExecutor = ThreadPoolExecutor


async def disk_call(function, *args, **kwargs):
    ensure_thread_executor()
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A thread cannot be forcibly cancelled. Its file mutation must finish
        # before rollback, restore-view discard or temporary-file cleanup.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not task.cancelled():
            # The worker may have failed between cancellation and the loop's
            # first condition. Retrieve that exception even when no await ran.
            task.exception()
        raise
