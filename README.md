# limpet

Mirror an existing iTerm2 session over an authenticated WebSocket, with screen
updates, keyboard input and resizing.

Limpet lets a terminal client attach to a session already open on your Mac. It
reads iTerm2's visible grid, converts changed rows to ANSI, and sends input back
to the selected session. It is a Python bridge for client developers and people
accessing their own terminals. A terminal UI is not included.

## Try the protocol locally

Python 3.10 or later is required. This example starts a temporary loopback
server, authenticates a client and exchanges synthetic screen and input frames.
It does not connect to iTerm2 or execute shell input.

```sh
git clone https://github.com/yuri-rod/limpet.git
cd limpet
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python examples/local_demo.py
```

Expected output:

```text
protocol: 2
sessions: demo
grid: 80x24
screen: synthetic terminal
input: 'hello\n'
ping: pong
```

The [example](examples/local_demo.py) uses the same
[WebSocket server](src/limpet/server.py) as the iTerm2 bridge and closes it on exit.

## Connect to iTerm2

The live bridge requires macOS, a running iTerm2 instance and access to its
[Python scripting API](https://iterm2.com/python-api/tutorial/index.html).
Install from the repository as above, then create
`~/.config/limpet/config.json`:

```json
{"host": "127.0.0.1", "port": 8737}
```

Run `limpet --dev` to bind to loopback. On first run, Limpet creates a random
256-bit token at `~/.config/limpet/token` with mode `0600`. Clients connect to
`ws://127.0.0.1:8737` and send `Authorization: Bearer <token>` in the handshake.
`LIMPET_CONFIG_DIR` changes the configuration and token directory.

Anyone with the token can read terminal contents and send commands as your
user. Use loopback or an encrypted private network. For a private network, set
`host` to that interface's IP and run `limpet` without `--dev`. Unspecified IP
addresses, including alternate spellings of `0.0.0.0` and `::`, are rejected.
The transport is plain WebSocket. See [SECURITY.md](SECURITY.md) before making
it reachable from another machine.

## Client workflow

Each WebSocket message is a JSON object. The server first sends `hello` with
`proto: 2`; clients should check that version before proceeding. Once iTerm2 has
been enumerated, `sessions` supplies session IDs, titles, jobs and paths.

```json
{"type":"subscribe","session":"SESSION_ID"}
{"type":"input","session":"SESSION_ID","text":"hello\n"}
{"type":"resize","session":"SESSION_ID","cols":80,"rows":24}
{"type":"unsubscribe","session":"SESSION_ID"}
```

Subscribe before sending input or resize requests. The server sends `grid` for
terminal dimensions and `screen` with ANSI text and a `reset` flag. A new
subscriber receives a snapshot; joining an existing mirror replays its latest
frame. Multiple clients can subscribe to a session. The last unsubscribe or
client disconnect stops that mirror and attempts to restore its original size.

`new_tab` creates a tab in the current iTerm2 window and replies with
`tab_created`; `ping` replies with `pong`. `session_gone` reports an unavailable
session. Invalid messages return `error`. Callback failures are logged; a failed
new-tab request currently has no dedicated error reply.
[protocol.py](src/limpet/protocol.py) defines message fields and validation.

## Implementation and operating limits

- [frames.py](src/limpet/frames.py) groups styled cells and emits changed rows,
  preserving double-width glyphs and combining characters. Terminal control
  bytes in cell text become blanks.
- [mirror.py](src/limpet/mirror.py) seeds quiet sessions with a snapshot and
  refreshes idle mirrors every ten seconds. Keyboard input suppresses iTerm2
  broadcast mode.
- [iterm.py](src/limpet/iterm.py) tracks sessions, layout, focus and tab titles.
  [main.py](src/limpet/main.py) checks the iTerm2 connection and exits on failure.

Only the visible grid is mirrored; scrollback and application transcripts are
not transmitted. Resizing changes the source terminal for every viewer. Split
panes and fullscreen windows may refuse resizing. Restoration needs a running
bridge and iTerm2 connection; process crashes cannot restore geometry.

The optional [launchd template](templates/com.example.limpet.plist.template)
restarts unsuccessful exits with a ten-second throttle. Replace `PYTHON` with
the virtual environment's interpreter path before installing it. Test the
configuration in the foreground first: invalid configuration also exits
nonzero and will be retried by launchd.

## Development

```sh
python -m pytest -q
python -m pip install ruff==0.16.5
ruff check src tests examples
ruff format --check src tests examples
```

Tests use synthetic iTerm2 objects and temporary loopback WebSocket servers.
They cover authentication, per-client subscriptions, malformed messages,
rendering, resize restoration and mirror recovery. They do not exercise a live
iTerm2 installation. CI runs Python 3.10 through 3.13 and checks the minimum
supported WebSocket version on Python 3.10.

Bug reports should include a reproducible example without private terminal
contents. Include a regression test when changing protocol or recovery behavior.

## Releases

GitHub releases provide versioned source independently of PyPI. To publish a
package, first configure a PyPI trusted publisher for `yuri-rod/limpet`, workflow
`publish.yml`, and environment `pypi`. Then manually run the publish workflow
from `main`, selecting the existing release tag:

```sh
gh workflow run publish.yml --ref main -f release_tag=v0.1.1
```

This command uploads the selected version to PyPI. The workflow checks out the
tag and rejects a tag that does not match the package version. A GitHub release
alone does not upload a package.

See [CHANGELOG.md](CHANGELOG.md) for version history.
Limpet is independent of the iTerm2 project. Licensed under [MIT](LICENSE).
