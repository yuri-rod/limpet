import json


class ProtocolError(Exception):
    pass


def hello(iterm2_version):
    return json.dumps({"type": "hello", "iterm2": iterm2_version, "proto": 2})


def sessions(rows):
    return json.dumps({"type": "sessions", "list": rows})


def grid(session_id, cols, rows):
    return json.dumps({"type": "grid", "session": session_id, "cols": cols, "rows": rows})


def screen(session_id, ansi, reset):
    return json.dumps({"type": "screen", "session": session_id, "reset": reset, "ansi": ansi})


def session_gone(session_id):
    return json.dumps({"type": "session_gone", "session": session_id})


def tab_created(session_id):
    return json.dumps({"type": "tab_created", "session": session_id})


def pong():
    return json.dumps({"type": "pong"})


_CLIENT_FIELDS = {
    "subscribe": (("session", str),),
    "unsubscribe": (("session", str),),
    "input": (("session", str), ("text", str)),
    "resize": (("session", str), ("cols", int), ("rows", int)),
    "new_tab": (),
    "ping": (),
}


def parse(text):
    try:
        msg = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"bad json: {e}") from e
    if not isinstance(msg, dict) or msg.get("type") not in _CLIENT_FIELDS:
        raise ProtocolError(f"unknown message type: {msg!r:.80}")
    for field, kind in _CLIENT_FIELDS[msg["type"]]:
        value = msg.get(field)
        # json true arrives as an int subclass, so a bare isinstance would let
        # {"cols": true} through as a cell count
        if kind is int and isinstance(value, bool) or not isinstance(value, kind):
            raise ProtocolError(f"{msg['type']} needs {kind.__name__} {field}")
        if kind is int and value < 1:
            raise ProtocolError(f"{msg['type']} needs a positive {field}")
    return msg
