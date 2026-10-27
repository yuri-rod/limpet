from collections import defaultdict
import hmac
import http
import json
import logging

from websockets.asyncio.server import serve

from . import protocol

log = logging.getLogger("limpet.server")


class BridgeServer:
    def __init__(
        self,
        token,
        iterm2_version,
        on_subscribe,
        on_unsubscribe,
        on_input,
        on_resize,
        on_new_tab,
    ):
        self._token = token
        self._iterm2_version = iterm2_version
        self._on_subscribe = on_subscribe
        self._on_unsubscribe = on_unsubscribe
        self._on_input = on_input
        self._on_resize = on_resize
        self._on_new_tab = on_new_tab
        self._server = None
        self._clients = set()
        self._subs = defaultdict(set)
        self._sessions_cache = None

    def _check_auth(self, connection, request):
        got = request.headers.get("Authorization", "").encode("utf-8", "replace")
        expected = f"Bearer {self._token}".encode()
        if not hmac.compare_digest(got, expected):
            log.warning("rejected connection with bad token")
            return connection.respond(http.HTTPStatus.UNAUTHORIZED, "denied\n")
        return None

    async def start(self, host, port):
        self._server = await serve(self._handler, host, port, process_request=self._check_auth)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws):
        self._clients.add(ws)
        try:
            await ws.send(protocol.hello(self._iterm2_version))
            # nothing has been enumerated yet right after a daemon restart;
            # an empty list here would dismiss whatever the phone is showing
            if self._sessions_cache is not None:
                await ws.send(protocol.sessions(self._sessions_cache))
            async for raw in ws:
                try:
                    msg = protocol.parse(raw)
                except protocol.ProtocolError as e:
                    log.warning("protocol error: %s", e)
                    await ws.send(json.dumps({"type": "error", "msg": str(e)}))
                    continue
                await self._dispatch(ws, msg)
        finally:
            self._clients.discard(ws)
            for sid in [s for s, subs in self._subs.items() if ws in subs]:
                await self._drop_sub(ws, sid)

    async def _dispatch(self, ws, msg):
        t = msg["type"]
        if t in {"input", "resize"} and ws not in self._subs.get(msg["session"], ()):
            await ws.send(
                json.dumps({"type": "error", "msg": "subscribe to the session first"})
            )
            return
        if t == "subscribe":
            sid = msg["session"]
            self._subs[sid].add(ws)
            # fires even when the mirror is already running: that is how a
            # late subscriber gets the current screen replayed to it
            await self._safe_callback(self._on_subscribe(sid), "on_subscribe")
        elif t == "unsubscribe":
            await self._drop_sub(ws, msg["session"])
        elif t == "input":
            await self._safe_callback(self._on_input(msg["session"], msg["text"]), "on_input")
        elif t == "resize":
            await self._safe_callback(
                self._on_resize(msg["session"], msg["cols"], msg["rows"]), "on_resize"
            )
        elif t == "new_tab":
            sid = await self._safe_callback(self._on_new_tab(), "on_new_tab")
            # a tab_created for a tab that was never created would send the
            # phone chasing a session id that does not exist
            if sid:
                await ws.send(protocol.tab_created(sid))
        elif t == "ping":
            await ws.send(protocol.pong())

    async def _safe_callback(self, coro, name):
        try:
            return await coro
        except Exception:
            log.exception("%s callback raised", name)
            return None

    def has_subscribers(self, sid):
        return bool(self._subs.get(sid))

    async def _drop_sub(self, ws, sid):
        subs = self._subs.get(sid)
        if not subs or ws not in subs:
            return
        subs.discard(ws)
        if not subs:
            del self._subs[sid]
            await self._safe_callback(self._on_unsubscribe(sid), "on_unsubscribe")

    async def _send_to(self, targets, text, sid=None):
        for ws in list(targets):
            try:
                await ws.send(text)
            except Exception:
                self._clients.discard(ws)
                if sid is not None:
                    await self._drop_sub(ws, sid)

    async def publish_sessions(self, rows):
        self._sessions_cache = rows
        await self._send_to(self._clients, protocol.sessions(rows))

    async def publish_screen(self, sid, ansi, reset):
        await self._send_to(self._subs.get(sid, ()), protocol.screen(sid, ansi, reset), sid=sid)

    async def publish_grid(self, sid, cols, rows):
        await self._send_to(self._subs.get(sid, ()), protocol.grid(sid, cols, rows), sid=sid)

    async def publish_gone(self, sid):
        await self._send_to(self._clients, protocol.session_gone(sid))
        for ws in list(self._subs.get(sid, ())):
            await self._drop_sub(ws, sid)
