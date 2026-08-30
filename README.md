# limpet

Mirror a terminal session that is **already running**.

A limpet clamps onto a hull that is already at sea. This one clamps onto an
iTerm2 session you opened hours ago, never prepared in any way, and streams it
to whatever client you point at it — over an authenticated WebSocket, with
keystrokes going back the other way.

That is the whole pitch, and it is the one thing the alternatives cannot do.
`ttyd`, `gotty`, Zellij's web client and every tmux-based sharing trick can only
serve a session **they** created, or one you remembered to start inside a
multiplexer. limpet needs neither. The session is already there; it attaches.

Zero runtime dependencies beyond the iTerm2 Python API and `websockets`.
About 1200 lines with 76 tests.

```
  iTerm2 session (already running)
        |
        |  ScreenStreamer, style=True
        v
  limpet  ── diffs frames, synthesises ANSI ──┐
        ^                                     │
        |  async_send_text                    │  authenticated WebSocket
        |                                     v
        └───────────────────────────── your client
```

## What you get

- **Live mirror of a running session**, full colour, as synthesised ANSI (SGR,
  CUP, ED, EL). The remote grid is authoritative; a client can be a dumb renderer.
- **Keystrokes back**, via `async_send_text` with broadcast suppressed.
- **Resize**, so the source session can be fitted to a phone-sized grid. The
  original geometry is stashed and restored on unsubscribe.
- **Remote new tab**, answered with the created session id.
- **A versioned wire protocol.** The `hello` frame carries `proto`, and a client
  is expected to refuse a version it does not speak.

## Honest limits

These are consequences of the approach, not bugs waiting for a fix. Read them
before you decide this is the right tool.

- **No scrollback.** limpet sends the visible grid, nothing above it. iTerm2's
  Python API reports `number_of_lines_above_screen` as always `0`
  ([iTerm2#8245](https://github.com/gnachman/iTerm2/issues/8245)), so the history
  is not reachable from this side at all.
- **No history for full-screen programs, ever.** `vim`, `htop`, `less`, and TUI
  agents hold the alternate screen, which has no scrollback in any terminal or
  multiplexer. If you need to read back through such a session, mirroring the
  terminal is the wrong mechanism — read that program's own transcript instead.
- **One mirror at a time**, by design. A second subscriber to a running mirror
  sees nothing until the next change or the 10-second repaint.
- **iTerm2 only, macOS only.** The attach mechanism is iTerm2's scripting API.
- **iTerm2 must be running.** When it quits, the daemon exits on purpose so the
  supervisor restarts it and reconnects.

## Install

```
pip install limpet
```

Then write `~/.config/limpet/config.json`:

```json
{
  "host": "100.64.0.2",
  "port": 8737
}
```

`host` must be an address you actually want this reachable on — a Tailscale or
VPN address, or `127.0.0.1`. Binding to `0.0.0.0` or `::` is refused outright;
see [SECURITY.md](SECURITY.md) for why. `limpet --dev` forces loopback.

```
limpet
```

A 64-hex-character token is generated at `~/.config/limpet/token` (mode `0600`)
on first run. Clients send it as `Authorization: Bearer <token>`.

## Running it as a daemon

`templates/com.example.limpet.plist.template` is a launchd agent. Substitute
`PYTHON` for your interpreter path and drop it in `~/Library/LaunchAgents/`.

Its `KeepAlive` is deliberately `SuccessfulExit: false` rather than a bare
`true`. limpet exits non-zero when the iTerm2 link dies, and that exit *is* the
reconnect strategy — but a bare `true` also restarts a process that died on a
bad config, in a tight loop, forever.

## Protocol

Server frames: `hello`, `sessions`, `grid`, `screen`, `session_gone`,
`tab_created`, `pong`.
Client frames: `subscribe`, `unsubscribe`, `input`, `resize`, `new_tab`, `ping`.

All JSON, one object per message. `protocol.py` is 70 lines and is the spec.

## Tests

```
pip install -e ".[dev]"
python -m pytest -q
```

## Not affiliated with iTerm2

limpet is an unaffiliated third-party tool. It talks to iTerm2 through the
public scripting API and is not endorsed by, or connected to, the iTerm2
project. "iTerm2" is used here only to say what limpet is compatible with.

## License

MIT. See [LICENSE](LICENSE).
