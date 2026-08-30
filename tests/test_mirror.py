import asyncio

from limpet import mirror as mirror_mod
from limpet.mirror import MirrorManager


class FakeServer:
    def __init__(self):
        self.screens = []
        self.grids = []
        self.gone = []

    async def publish_screen(self, sid, ansi, full):
        self.screens.append((sid, ansi, full))

    async def publish_grid(self, sid, cols, rows):
        self.grids.append((sid, cols, rows))

    async def publish_gone(self, sid):
        self.gone.append(sid)


class SwapStreamer:
    """Its async_get raises like a real stream that hit an RPC error, but
    that only happens if the loop actually reaches it: _stream takes a seed
    snapshot before ever touching the streamer, so pair this with a session
    whose async_get_screen_contents succeeds if the test needs this raise to
    be what kills the stream. __aexit__ runs regardless of which of the two
    raised (any exception leaving the `async with` block triggers it) and
    optionally mutates the manager's task registry before the exception
    keeps propagating, standing in for a concurrent stop+start that lands
    while a dying task is still unwinding through ScreenStreamer.__aexit__
    (a genuine asyncio cancellation race is flaky to force deterministically
    in a test, so we simulate its effect on the registry directly)."""

    def __init__(self, manager, sid, replacement=None):
        self.manager = manager
        self.sid = sid
        self.replacement = replacement

    async def __aenter__(self):
        return self

    async def async_get(self, style=True):
        raise RuntimeError("boom")

    async def __aexit__(self, exc_type, exc, tb):
        if self.replacement is not None:
            self.manager._tasks[self.sid] = self.replacement
        return False


class SimpleSession:
    """Its seed snapshot raises immediately, before the streamer is ever
    awaited."""

    def __init__(self, streamer):
        self._streamer = streamer

    def get_screen_streamer(self):
        return self._streamer

    async def async_get_screen_contents(self):
        raise RuntimeError("boom")


class SeededSession:
    """Its seed snapshot succeeds, so a later stream error has to come from
    the streamer itself (SwapStreamer.async_get), not from the seed."""

    def __init__(self, streamer, contents, cols=10):
        self._streamer = streamer
        self._contents = contents
        self.grid_size = FakeGridSize(cols)

    def get_screen_streamer(self):
        return self._streamer

    async def async_get_screen_contents(self):
        return self._contents


async def test_stream_error_cleanup_does_not_evict_newer_task():
    # failure point: the seed snapshot raises
    server = FakeServer()
    manager = MirrorManager(app=None, server=server)
    sid = "S1"
    replacement_task = object()
    streamer = SwapStreamer(manager, sid, replacement=replacement_task)
    session = SimpleSession(streamer)

    dying = asyncio.create_task(manager._stream(sid, session))
    manager._tasks[sid] = dying
    await dying

    assert manager._tasks[sid] is replacement_task
    assert server.gone == [sid]


async def test_stream_error_cleanup_evicts_own_registration():
    # failure point: the seed succeeds and SwapStreamer.async_get raises
    server = FakeServer()
    manager = MirrorManager(app=None, server=server)
    sid = "S1"
    streamer = SwapStreamer(manager, sid, replacement=None)
    contents = FakeContents(["hello"])
    session = SeededSession(streamer, contents)
    manager.app = FakeApp(session)

    dying = asyncio.create_task(manager._stream(sid, session))
    manager._tasks[sid] = dying
    await dying

    assert sid not in manager._tasks
    assert server.gone == [sid]
    # the seed itself published before the streamer's error killed the loop
    assert server.screens and "hello" in server.screens[0][1]


class FakePoint:
    def __init__(self, x, y):
        self.x, self.y = x, y


class FakeLine:
    def __init__(self, text):
        self.string = text

    def style_at(self, x):
        return None

    def string_at(self, x):
        return self.string[x]


class FakeContents:
    def __init__(self, lines):
        self._lines = [FakeLine(t) for t in lines]
        self.number_of_lines = len(self._lines)
        self.cursor_coord = FakePoint(0, 0)

    def line(self, i):
        return self._lines[i]


class FakeGridSize:
    def __init__(self, width):
        self.width = width


class HangingStreamer:
    """Its async_get never resolves on its own, so every iteration falls
    through to the wait_for timeout, like a session that stopped emitting
    updates."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def async_get(self, style=True):
        await asyncio.Event().wait()


class IdleSession:
    """HangingStreamer never resolves, so every frame after the first can
    only come from the quiet-timeout snapshot poll in async_get_screen_contents.
    Pass a single contents object to return it on every call, or a sequence
    to return one per call (holding the last for any call past the end) so a
    test can tell the seed snapshot apart from a later fallback one."""

    def __init__(self, contents, cols=10):
        self._contents_seq = (
            list(contents) if isinstance(contents, (list, tuple)) else [contents]
        )
        self._calls = 0
        self.grid_size = FakeGridSize(cols)

    def get_screen_streamer(self):
        return HangingStreamer()

    async def async_get_screen_contents(self):
        i = min(self._calls, len(self._contents_seq) - 1)
        self._calls += 1
        return self._contents_seq[i]


class FakeApp:
    def __init__(self, session, window=None):
        self.session = session
        self.current_terminal_window = window

    def get_session_by_id(self, sid):
        return self.session


async def test_idle_session_republishes_after_quiet_timeout(monkeypatch):
    monkeypatch.setattr(mirror_mod, "FULL_REPAINT_EVERY", 0.05)
    seed = FakeContents(["hello"])
    fallback = FakeContents(["world"])
    session = IdleSession([seed, fallback])
    server = FakeServer()
    manager = MirrorManager(FakeApp(session), server)

    await manager.start("S1")
    for _ in range(100):
        if len(server.screens) >= 2:
            break
        await asyncio.sleep(0.02)
    await manager.stop("S1")

    # the first frame is the subscribe-time seed; only a second frame,
    # with different content, proves the wait_for timeout fallback ran
    assert len(server.screens) >= 2, (
        "expected the quiet-timeout fallback to publish a second frame"
    )
    assert "hello" in server.screens[0][1]
    assert "world" in server.screens[1][1]


async def test_first_frame_does_not_wait_for_a_stream_event():
    contents = FakeContents(["hello"])
    session = IdleSession(contents)
    server = FakeServer()
    manager = MirrorManager(FakeApp(session), server)

    await manager.start("S1")
    for _ in range(20):
        if server.screens:
            break
        await asyncio.sleep(0.01)
    await manager.stop("S1")

    # FULL_REPAINT_EVERY is untouched here, so a frame this soon can only have
    # come from the subscribe-time snapshot, not from the repaint timer
    assert server.screens, "subscribing to a quiet session must seed the mirror"
    assert server.screens[0][2] is True
    assert "hello" in server.screens[0][1]
    assert server.grids == [("S1", 10, 1)]


async def test_late_subscriber_gets_the_screen_replayed():
    session = IdleSession(FakeContents(["hello"]))
    server = FakeServer()
    manager = MirrorManager(FakeApp(session), server)

    await manager.start("S1")
    for _ in range(20):
        if server.screens:
            break
        await asyncio.sleep(0.01)
    first_screens, first_grids = len(server.screens), len(server.grids)

    await manager.start("S1")
    await manager.stop("S1")

    assert len(server.screens) == first_screens + 1
    assert len(server.grids) == first_grids + 1
    sid, ansi, full = server.screens[-1]
    assert sid == "S1" and full and "hello" in ansi


async def test_replay_before_any_frame_is_a_no_op():
    session = IdleSession(FakeContents(["hello"]))
    server = FakeServer()
    manager = MirrorManager(FakeApp(session), server)
    manager._tasks["S1"] = asyncio.create_task(asyncio.sleep(5))

    await manager.start("S1")
    await manager.stop("S1")

    assert server.screens == [] and server.grids == []


class FakeSize:
    def __init__(self, width, height):
        self.width, self.height = width, height


class ResizableSession:
    def __init__(self, cols=200, rows=50):
        self.grid_size = FakeSize(cols, rows)
        self.sizes = []

    async def async_set_grid_size(self, size):
        self.sizes.append((size.width, size.height))
        self.grid_size = FakeSize(size.width, size.height)


class FakeNewSession:
    def __init__(self, sid):
        self.session_id = sid


class FakeTab:
    def __init__(self, sid):
        self.current_session = FakeNewSession(sid)


class FakeWindow:
    def __init__(self, tab):
        self._tab = tab
        self.created = 0

    async def async_create_tab(self):
        self.created += 1
        return self._tab


async def test_resize_shrinks_the_session_and_stop_restores_it():
    session = ResizableSession(200, 50)
    manager = MirrorManager(FakeApp(session), FakeServer())

    await manager.resize("S1", 60, 20)
    assert session.sizes == [(60, 20)]

    await manager.stop("S1")
    assert session.sizes == [(60, 20), (200, 50)]


async def test_resizing_twice_still_restores_the_mac_size():
    # the second resize must not record the phone's own grid as the original
    session = ResizableSession(200, 50)
    manager = MirrorManager(FakeApp(session), FakeServer())

    await manager.resize("S1", 60, 20)
    await manager.resize("S1", 55, 18)
    await manager.stop("S1")

    assert session.sizes[-1] == (200, 50)


async def test_stop_without_a_resize_leaves_the_grid_alone():
    session = ResizableSession(200, 50)
    manager = MirrorManager(FakeApp(session), FakeServer())

    await manager.stop("S1")

    assert session.sizes == []


async def test_resize_on_a_dead_session_reports_it_gone():
    server = FakeServer()
    manager = MirrorManager(FakeApp(None), server)

    await manager.resize("S1", 60, 20)

    assert server.gone == ["S1"]


async def test_new_tab_returns_the_new_session_id():
    window = FakeWindow(FakeTab("S9"))
    manager = MirrorManager(FakeApp(None, window), FakeServer())

    assert await manager.new_tab() == "S9"
    assert window.created == 1


async def test_new_tab_without_a_window_returns_nothing():
    manager = MirrorManager(FakeApp(None, None), FakeServer())

    assert await manager.new_tab() is None
