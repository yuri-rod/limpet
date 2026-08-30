import asyncio

from limpet.iterm import SessionTracker


async def test_dead_title_watcher_is_revived_on_next_sync():
    async def publish(rows):
        pass

    tracker = SessionTracker(None, None, publish)

    async def dead_title(tab_id):
        return

    tracker._title = dead_title

    tracker._sync_title_watchers({"8"})
    first = tracker._title_tasks["8"]
    await asyncio.sleep(0)
    assert first.done()

    tracker._sync_title_watchers({"8"})
    second = tracker._title_tasks["8"]

    assert second is not first
    assert not second.done()
