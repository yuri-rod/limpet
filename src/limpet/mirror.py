import asyncio
import logging
import time

import iterm2

from . import frames

log = logging.getLogger("limpet.mirror")

FULL_REPAINT_EVERY = 10.0


class MirrorManager:
    def __init__(self, app, server):
        self.app = app
        self.server = server
        self._tasks = {}
        self._frames = {}
        self._grids = {}

    async def start(self, sid):
        if sid in self._tasks:
            await self._replay(sid)
            return
        session = self.app.get_session_by_id(sid)
        if session is None:
            await self.server.publish_gone(sid)
            return
        self._tasks[sid] = asyncio.create_task(self._stream(sid, session))

    async def _replay(self, sid):
        """Repaint for a subscriber that joined a mirror already in flight.

        It missed the grid message and every frame so far, so without this it
        stares at a blank screen until the session next changes.
        """
        frame = self._frames.get(sid)
        if frame is None:
            return
        await self.server.publish_grid(sid, frame.cols, frame.rows)
        ansi, _ = frames.render(None, frame, True)
        if ansi:
            await self.server.publish_screen(sid, ansi, True)

    async def stop(self, sid):
        await self._restore_grid(sid)
        self._frames.pop(sid, None)
        task = self._tasks.pop(sid, None)
        if task:
            task.cancel()

    async def stop_all(self):
        for sid in dict.fromkeys(list(self._tasks) + list(self._grids)):
            await self.stop(sid)

    async def resize(self, sid, cols, rows):
        session = self.app.get_session_by_id(sid)
        if session is None:
            await self.server.publish_gone(sid)
            return
        was = (session.grid_size.width, session.grid_size.height)
        try:
            await session.async_set_grid_size(iterm2.util.Size(cols, rows))
        except Exception as e:
            # split panes and fullscreen windows refuse to be resized
            log.warning("resize of %s to %dx%d failed: %s", sid, cols, rows, e)
            return
        # setdefault, so a second resize does not record the phone's own grid
        # as the size to go home to
        self._grids.setdefault(sid, was)

    async def new_tab(self):
        window = self.app.current_terminal_window
        if window is None:
            log.warning("new tab requested with no terminal window open")
            return None
        tab = await window.async_create_tab()
        return tab.current_session.session_id

    async def _restore_grid(self, sid):
        size = self._grids.pop(sid, None)
        if size is None:
            return
        session = self.app.get_session_by_id(sid)
        if session is None:
            return
        try:
            await session.async_set_grid_size(iterm2.util.Size(*size))
        except Exception as e:
            log.warning("could not restore %s to %dx%d: %s", sid, *size, e)

    async def send_input(self, sid, text):
        session = self.app.get_session_by_id(sid)
        if session is None:
            await self.server.publish_gone(sid)
            return
        await session.async_send_text(text, suppress_broadcast=True)

    async def _stream(self, sid, session):
        prev = None
        last_full = 0.0
        last_grid = None
        try:
            async with session.get_screen_streamer() as streamer:
                seeded = False
                while True:
                    if not seeded:
                        # a quiet session emits no stream event, so a fresh
                        # subscriber would stare at an empty mirror until the
                        # repaint timer fired; seed it from a snapshot instead
                        seeded = True
                        contents = await session.async_get_screen_contents()
                        if contents is None:
                            log.info(
                                "mirror %s: seed snapshot came back empty, "
                                "falling back to the stream",
                                sid,
                            )
                    else:
                        try:
                            contents = await asyncio.wait_for(
                                streamer.async_get(style=True), timeout=FULL_REPAINT_EVERY
                            )
                        except asyncio.TimeoutError:
                            # session went quiet; ScreenStreamer drops deltas
                            # that arrive while we're not awaiting it, so poll
                            # directly instead of parking here forever
                            contents = await session.async_get_screen_contents()
                    if contents is None:
                        continue
                    # App refresh mutates the existing Session object in
                    # place (update_from), so this is just a cheap
                    # consistency guard, not what keeps grid_size fresh
                    session = self.app.get_session_by_id(sid) or session
                    cols = session.grid_size.width
                    frame = frames.from_screen_contents(contents, cols)
                    grid = (frame.cols, frame.rows)
                    if grid != last_grid:
                        last_grid = grid
                        await self.server.publish_grid(sid, *grid)
                    now = time.monotonic()
                    force = now - last_full > FULL_REPAINT_EVERY
                    ansi, full = frames.render(prev, frame, force)
                    prev = self._frames[sid] = frame
                    if full:
                        last_full = now
                    if ansi:
                        await self.server.publish_screen(sid, ansi, full)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("mirror %s died: %s", sid, e)
            if self._tasks.get(sid) is asyncio.current_task():
                del self._tasks[sid]
                self._frames.pop(sid, None)
            await self.server.publish_gone(sid)
