# Security

A Limpet token gives access to live terminal contents and command input as the
user running the bridge. There is no sandbox, command filtering, read-only
credential or per-session access policy.

## Authentication and transport

The first run creates a random 256-bit bearer token in
`~/.config/limpet/token` with mode `0600`. Clients send it in the
`Authorization` header. Missing or incorrect credentials receive HTTP 401
before the WebSocket connection is accepted.

The token has no expiry or per-client revocation. To rotate it, stop the bridge,
remove the token file, restart and update clients with the new token. Stopping
the bridge closes existing connections; editing the token file alone does not
revoke them.

Limpet serves plain `ws://`. Use loopback (`127.0.0.1`, or `--dev`) or an
encrypted private network such as Tailscale or WireGuard. Public tunnels are
unsupported. A proxy can see both the token and terminal traffic.

Configuration rejects empty hosts and unspecified IP literals, including
expanded IPv6 and alternate numeric IPv4 forms. Use an explicit interface IP;
hostnames depend on your resolver and may change which interface is selected.

## Terminal contents and input

Subscribers receive the full visible grid, including any credentials or private
data displayed there. Limpet does not redact sensitive text. Visible-grid-only
mirroring is not an access control: a client can send commands that display
other files or history.

Input and resize messages require that the sending client is subscribed to the
target session. This keeps mutations tied to the subscription lifecycle so
resize restoration can run when the last subscriber leaves. Any token holder
can subscribe to any available session or request a new tab.

Invalid JSON and invalid message fields receive a protocol error. WebSocket
messages use the library's default 1 MiB receive limit. There is no per-client
rate limit. Use only trusted clients.

## Reporting

Open a GitHub issue for non-sensitive problems. For a vulnerability that should
remain private, use the repository's private security advisory form.
