import asyncio
import json
import logging

import pytest
import websockets
from websockets.asyncio.client import connect

from limpet.server import BridgeServer

TOKEN = "sekrit"


class Spy:
    def __init__(self):
        self.subs, self.unsubs, self.inputs = [], [], []
        self.resizes, self.new_tabs = [], 0

    async def on_subscribe(self, sid):
        self.subs.append(sid)

    async def on_unsubscribe(self, sid):
        self.unsubs.append(sid)

    async def on_input(self, sid, text):
        self.inputs.append((sid, text))

    async def on_resize(self, sid, cols, rows):
        self.resizes.append((sid, cols, rows))

    async def on_new_tab(self):
        self.new_tabs += 1
        return "NEW"


@pytest.fixture
async def srv():
    spy = Spy()
    s = BridgeServer(
        TOKEN,
        "3.6.11",
        spy.on_subscribe,
        spy.on_unsubscribe,
        spy.on_input,
        spy.on_resize,
        spy.on_new_tab,
    )
    port = await s.start("127.0.0.1", 0)
    yield s, spy, f"ws://127.0.0.1:{port}"
    await s.stop()


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


async def _hello(ws):
    msg = json.loads(await ws.recv())
    assert msg["type"] == "hello"
    return msg


async def test_rejects_bad_token(srv):
    _, _, url = srv
    with pytest.raises(websockets.exceptions.InvalidStatus) as e:
        await connect(url, additional_headers=_headers("wrong"))
    assert e.value.response.status_code == 401


async def test_rejects_non_ascii_token_with_401_not_500(srv):
    _, _, url = srv
    with pytest.raises(websockets.exceptions.InvalidStatus) as e:
        await connect(url, additional_headers=_headers("wrongéè"))
    assert e.value.response.status_code == 401


async def test_hello_and_cached_sessions_on_connect(srv):
    s, _, url = srv
    await s.publish_sessions([{"id": "S1"}])
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        msg = json.loads(await ws.recv())
        assert msg["type"] == "sessions" and msg["list"] == [{"id": "S1"}]


async def test_subscribe_input_unsubscribe_flow(srv):
    s, spy, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send('{"type":"subscribe","session":"S1"}')
        await ws.send('{"type":"input","session":"S1","text":"ls\\n"}')
        for _ in range(50):
            if spy.inputs:
                break
            await asyncio.sleep(0.02)
        assert spy.subs == ["S1"] and spy.inputs == [("S1", "ls\n")]
        assert s.has_subscribers("S1")
        await s.publish_screen("S1", "\x1b[2J", reset=True)
        assert json.loads(await ws.recv())["type"] == "screen"
    for _ in range(50):
        if spy.unsubs:
            break
        await asyncio.sleep(0.02)
    assert spy.unsubs == ["S1"]
    assert not s.has_subscribers("S1")


async def test_garbage_gets_error_not_crash(srv):
    _, _, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send("garbage")
        msg = json.loads(await ws.recv())
        assert msg["type"] == "error"


@pytest.mark.parametrize("raw", ['{"type":[]}', b"\xff"])
async def test_malformed_message_keeps_connection_usable(srv, raw):
    _, _, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send(raw)
        assert json.loads(await ws.recv())["type"] == "error"
        await ws.send('{"type":"ping"}')
        assert json.loads(await ws.recv())["type"] == "pong"


@pytest.mark.parametrize(
    "message",
    [
        {"type": "input", "session": "S1", "text": "synthetic input"},
        {"type": "resize", "session": "S1", "cols": 80, "rows": 24},
    ],
)
async def test_session_writes_require_the_sending_clients_subscription(srv, message):
    _, spy, url = srv
    async with (
        connect(url, additional_headers=_headers()) as owner,
        connect(url, additional_headers=_headers()) as other,
    ):
        await _hello(owner)
        await _hello(other)
        await owner.send('{"type":"subscribe","session":"S1"}')
        await owner.send('{"type":"ping"}')
        assert json.loads(await owner.recv())["type"] == "pong"
        await other.send(json.dumps(message))
        await other.send('{"type":"ping"}')
        assert json.loads(await other.recv())["type"] == "error"
        assert json.loads(await other.recv())["type"] == "pong"
        assert spy.inputs == [] and spy.resizes == []

        await owner.send('{"type":"unsubscribe","session":"S1"}')
        await owner.send(json.dumps(message))
        await owner.send('{"type":"ping"}')
        assert json.loads(await owner.recv())["type"] == "error"
        assert json.loads(await owner.recv())["type"] == "pong"
        assert spy.inputs == [] and spy.resizes == []


class DeadSocket:
    async def send(self, text):
        raise ConnectionResetError("boom")


async def test_dead_subscriber_purged_on_publish_failure(srv):
    s, spy, _ = srv
    dead = DeadSocket()
    s._subs["S1"].add(dead)
    assert s.has_subscribers("S1")
    await s.publish_screen("S1", "\x1b[2J", reset=True)
    assert not s.has_subscribers("S1")
    assert spy.unsubs == ["S1"]


async def test_publish_gone_purges_subs_and_resubscribe_fires_again(srv):
    s, spy, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send('{"type":"subscribe","session":"S1"}')
        for _ in range(50):
            if spy.subs:
                break
            await asyncio.sleep(0.02)
        assert spy.subs == ["S1"]
        assert s.has_subscribers("S1")

        await s.publish_gone("S1")

        for _ in range(50):
            if spy.unsubs:
                break
            await asyncio.sleep(0.02)
        assert spy.unsubs == ["S1"]
        assert not s.has_subscribers("S1")

        await ws.send('{"type":"subscribe","session":"S1"}')
        for _ in range(50):
            if spy.subs == ["S1", "S1"]:
                break
            await asyncio.sleep(0.02)
        assert spy.subs == ["S1", "S1"]
        assert s.has_subscribers("S1")


async def test_on_input_exception_does_not_disconnect(caplog):
    async def boom(sid, text):
        raise RuntimeError("boom")

    spy = Spy()
    s = BridgeServer(
        TOKEN,
        "3.6.11",
        spy.on_subscribe,
        spy.on_unsubscribe,
        boom,
        spy.on_resize,
        spy.on_new_tab,
    )
    port = await s.start("127.0.0.1", 0)
    try:
        async with connect(f"ws://127.0.0.1:{port}", additional_headers=_headers()) as ws:
            await _hello(ws)
            await ws.send('{"type":"subscribe","session":"S1"}')
            with caplog.at_level(logging.ERROR, logger="limpet.server"):
                await ws.send('{"type":"input","session":"S1","text":"ls\\n"}')
                await ws.send('{"type":"ping"}')
                msg = json.loads(await ws.recv())
            assert msg["type"] == "pong"
        assert any("on_input" in r.getMessage() for r in caplog.records)
    finally:
        await s.stop()


async def test_no_sessions_frame_before_the_first_enumeration(srv):
    _, _, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send('{"type":"ping"}')
        # a "sessions": [] here would blank the phone's list on every restart
        assert json.loads(await ws.recv())["type"] == "pong"


async def test_empty_enumeration_is_still_published(srv):
    s, _, url = srv
    await s.publish_sessions([])
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        msg = json.loads(await ws.recv())
        assert msg["type"] == "sessions" and msg["list"] == []


async def test_second_subscriber_fires_on_subscribe_again(srv):
    s, spy, url = srv
    async with (
        connect(url, additional_headers=_headers()) as a,
        connect(url, additional_headers=_headers()) as b,
    ):
        await _hello(a)
        await _hello(b)
        await a.send('{"type":"subscribe","session":"S1"}')
        await b.send('{"type":"subscribe","session":"S1"}')
        for _ in range(50):
            if spy.subs == ["S1", "S1"]:
                break
            await asyncio.sleep(0.02)
        # the manager needs the second call to replay the screen to the
        # newcomer; without it that client sees nothing until the next change
        assert spy.subs == ["S1", "S1"]


async def test_resize_reaches_the_manager(srv):
    _, spy, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send('{"type":"subscribe","session":"S1"}')
        await ws.send('{"type":"resize","session":"S1","cols":80,"rows":24}')
        for _ in range(50):
            if spy.resizes:
                break
            await asyncio.sleep(0.02)
        assert spy.resizes == [("S1", 80, 24)]


async def test_new_tab_replies_with_the_created_session(srv):
    _, spy, url = srv
    async with connect(url, additional_headers=_headers()) as ws:
        await _hello(ws)
        await ws.send('{"type":"new_tab"}')
        assert json.loads(await ws.recv()) == {"type": "tab_created", "session": "NEW"}
        assert spy.new_tabs == 1


async def test_failed_new_tab_stays_quiet_and_keeps_the_socket(caplog):
    async def boom():
        raise RuntimeError("no window")

    spy = Spy()
    s = BridgeServer(
        TOKEN, "3.6.11", spy.on_subscribe, spy.on_unsubscribe, spy.on_input, spy.on_resize, boom
    )
    port = await s.start("127.0.0.1", 0)
    try:
        async with connect(f"ws://127.0.0.1:{port}", additional_headers=_headers()) as ws:
            await _hello(ws)
            with caplog.at_level(logging.ERROR, logger="limpet.server"):
                await ws.send('{"type":"new_tab"}')
                await ws.send('{"type":"ping"}')
                # a tab_created here would send the phone chasing a session
                # that was never created
                assert json.loads(await ws.recv())["type"] == "pong"
        assert any("on_new_tab" in r.getMessage() for r in caplog.records)
    finally:
        await s.stop()
