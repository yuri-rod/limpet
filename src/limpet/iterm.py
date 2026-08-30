import asyncio
import logging

import iterm2

log = logging.getLogger("limpet.iterm")


async def _var(obj, name):
    try:
        return await obj.async_get_variable(name) or ""
    except Exception as e:
        log.debug("variable %s unavailable: %s", name, e)
        return ""


async def build_sessions(app):
    active_id = None
    w = app.current_terminal_window
    if w and w.current_tab and w.current_tab.current_session:
        active_id = w.current_tab.current_session.session_id
    rows = []
    for win in app.windows:
        for tab in win.tabs:
            title = await _var(tab, "title")
            for s in tab.sessions:
                rows.append(
                    {
                        "id": s.session_id,
                        "title": title,
                        "job": await _var(s, "jobName"),
                        "path": await _var(s, "path"),
                        "tty": await _var(s, "tty"),
                        "window": str(win.window_id),
                        "tab": str(tab.tab_id),
                        "active": s.session_id == active_id,
                    }
                )
    return rows


class SessionTracker:
    def __init__(self, connection, app, publish):
        self.connection = connection
        self.app = app
        self.publish = publish
        self.terminated = asyncio.Queue()
        self._dirty = asyncio.Event()
        self._title_tasks = {}

    async def run(self):
        self._dirty.set()
        try:
            await asyncio.gather(
                self._publisher(),
                self._watch(iterm2.NewSessionMonitor),
                self._watch(iterm2.LayoutChangeMonitor),
                self._terminations(),
                self._focus(),
            )
        finally:
            for t in self._title_tasks.values():
                t.cancel()

    async def _publisher(self):
        last = None
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            await asyncio.sleep(0.5)
            rows = await build_sessions(self.app)
            self._sync_title_watchers({r["tab"] for r in rows})
            if rows != last:
                last = rows
                await self.publish(rows)

    async def _watch(self, monitor_cls):
        async with monitor_cls(self.connection) as mon:
            while True:
                await mon.async_get()
                self._dirty.set()

    async def _terminations(self):
        async with iterm2.SessionTerminationMonitor(self.connection) as mon:
            while True:
                sid = await mon.async_get()
                await self.terminated.put(sid)
                self._dirty.set()

    async def _focus(self):
        async with iterm2.FocusMonitor(self.connection) as mon:
            while True:
                await mon.async_get_next_update()
                self._dirty.set()

    def _sync_title_watchers(self, tab_ids):
        for tid, t in list(self._title_tasks.items()):
            if t.done():
                if not t.cancelled() and t.exception() is not None:
                    log.warning("title watcher for tab %s died: %s", tid, t.exception())
                del self._title_tasks[tid]
        for tid in tab_ids - self._title_tasks.keys():
            self._title_tasks[tid] = asyncio.create_task(self._title(tid))
        for tid in self._title_tasks.keys() - tab_ids:
            self._title_tasks.pop(tid).cancel()

    async def _title(self, tab_id):
        try:
            async with iterm2.VariableMonitor(
                self.connection, iterm2.VariableScopes.TAB, "title", tab_id
            ) as mon:
                while True:
                    await mon.async_get()
                    self._dirty.set()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("title watcher for tab %s died: %s", tab_id, e)
