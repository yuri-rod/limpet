# Security

Be blunt about what this is: **limpet hands a live shell to whoever holds the
token.** Keystrokes go straight into a real terminal session running as you, on
your machine. Treat the token like an SSH private key, and read this page before
you make it reachable from anywhere.

## What actually protects it

One bearer token. `secrets.token_hex(32)` — 256 bits — written to
`~/.config/limpet/token` at mode `0600` on first run, and sent by the client as
`Authorization: Bearer <token>`. Without it the WebSocket handshake is rejected.

There is no user model, no session expiry, no revocation list, and no second
factor. The token is compared against the expected value on every connection.
Rotating it means deleting the file and restarting; every existing client then
has to be reconfigured.

If you want revocable, named, or read-only credentials, limpet does not have
them. That is a real gap, and for some deployments it is disqualifying.

## The transport is plain WebSocket

`ws://`, not `wss://`. There is no TLS in limpet and none is planned, because
adding half-configured TLS is worse than being clear that there is none.

This means **the network path has to be the thing you trust.** Two supported
shapes:

- **Loopback only.** `limpet --dev`, or `"host": "127.0.0.1"`. Nothing leaves
  the machine.
- **A private overlay network.** A Tailscale or WireGuard address, where the
  transport is already encrypted and authenticated below limpet.

`config.py` refuses `0.0.0.0`, `::`, and an empty host outright, with an error
that names the problem. That check exists so a copy-pasted config cannot quietly
put an unencrypted remote shell on every interface of your machine. Do not work
around it.

Putting limpet behind a public tunnel is out of scope and unsupported. If you do
it anyway, you are publishing an unencrypted shell whose only guard is a string
in a query-free header, and any proxy in the path sees both.

## What the mirror publishes

Every subscriber sees the full visible content of the session it subscribed to,
as rendered text with colour. Whatever is on that screen — a token you just
echoed, a connection string, a client's data — goes over the wire. limpet does
not, and cannot, know what is sensitive.

It sends only the visible grid, not scrollback, which limits exposure to what is
on screen at that moment. That is a side effect of the design, not a security
feature. Do not rely on it.

## The write path

`input` frames become `async_send_text` calls into the real session. There is no
sandbox and no command filtering — that is the point of the tool, and it is also
the whole risk. Anything that can authenticate can run anything you can run.

The one constraint worth naming: keystrokes go to the session the client
subscribed to, and session ids are ephemeral, re-keyed whenever iTerm2 restarts.
A stale id fails rather than landing in a different session.

## Reporting

Open a GitHub issue for anything non-sensitive. For a vulnerability that should
not be public, use GitHub's private security advisory form on this repository.
