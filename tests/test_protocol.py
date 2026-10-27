import json

import pytest

from limpet import protocol


def test_server_messages_roundtrip():
    assert json.loads(protocol.hello("3.6.11")) == {
        "type": "hello",
        "iterm2": "3.6.11",
        "proto": 2,
    }
    row = {
        "id": "S1",
        "title": "t",
        "job": "zsh",
        "path": "/",
        "tty": "x",
        "window": "w",
        "tab": "8",
        "active": True,
    }
    assert json.loads(protocol.sessions([row]))["list"] == [row]
    assert json.loads(protocol.grid("S1", 224, 50)) == {
        "type": "grid",
        "session": "S1",
        "cols": 224,
        "rows": 50,
    }
    msg = json.loads(protocol.screen("S1", "\x1b[2J", reset=True))
    assert msg["reset"] is True and msg["ansi"] == "\x1b[2J"
    assert json.loads(protocol.session_gone("S1"))["session"] == "S1"
    assert json.loads(protocol.pong())["type"] == "pong"


def test_parse_valid_client_messages():
    assert protocol.parse('{"type":"subscribe","session":"S1"}') == {
        "type": "subscribe",
        "session": "S1",
    }
    got = protocol.parse('{"type":"input","session":"S1","text":"\\u0003"}')
    assert got["text"] == "\x03"
    assert protocol.parse('{"type":"ping"}') == {"type": "ping"}


def test_tab_created_carries_the_new_session():
    assert json.loads(protocol.tab_created("S9")) == {"type": "tab_created", "session": "S9"}


def test_parse_accepts_resize_and_new_tab():
    assert protocol.parse('{"type":"resize","session":"S1","cols":80,"rows":24}') == {
        "type": "resize",
        "session": "S1",
        "cols": 80,
        "rows": 24,
    }
    assert protocol.parse('{"type":"new_tab"}') == {"type": "new_tab"}


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        b"\xff",
        '{"type":[]}',
        '{"type":{}}',
        '{"type":"nope"}',
        '{"type":"subscribe"}',
        '{"type":"input","session":"S1"}',
        '{"type":"input","session":1,"text":"x"}',
        '{"type":"resize","session":"S1","cols":"80","rows":24}',
        # bool is an int subclass in python, so this one needs a deliberate guard
        '{"type":"resize","session":"S1","cols":true,"rows":24}',
        '{"type":"resize","session":"S1","cols":80}',
        '{"type":"resize","session":"S1","cols":0,"rows":24}',
        '{"type":"resize","session":"S1","cols":80,"rows":-1}',
    ],
)
def test_parse_rejects_garbage(bad):
    with pytest.raises(protocol.ProtocolError):
        protocol.parse(bad)
