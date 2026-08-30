import argparse
import asyncio
import logging
import sys

import iterm2

from . import config
from .iterm import SessionTracker
from .mirror import MirrorManager
from .server import BridgeServer

log = logging.getLogger("limpet")


async def _run_connected(cfg, host):
    connection = await iterm2.Connection.async_create()
    app = await iterm2.async_get_app(connection)
    try:
        version = await app.async_get_variable("iterm2Version") or "?"
    except Exception:
        version = "?"
    mirrors = None
    server = BridgeServer(
        cfg.token,
        version,
        on_subscribe=lambda sid: mirrors.start(sid),
        on_unsubscribe=lambda sid: mirrors.stop(sid),
        on_input=lambda sid, text: mirrors.send_input(sid, text),
        on_resize=lambda sid, cols, rows: mirrors.resize(sid, cols, rows),
        on_new_tab=lambda: mirrors.new_tab(),
    )
    mirrors = MirrorManager(app, server)
    port = await server.start(host, cfg.port)
    log.info("listening on %s:%s", host, port)
    tracker = SessionTracker(connection, app, server.publish_sessions)

    async def reap_terminated():
        while True:
            sid = await tracker.terminated.get()
            await mirrors.stop(sid)
            await server.publish_gone(sid)

    async def iterm_heartbeat():
        # the lib's dispatch loop dies silently when iTerm2 quits while our
        # monitors hang on queues it no longer feeds; probe the link so the
        # process actually exits and KeepAlive reconnects us
        while True:
            await asyncio.sleep(15)
            await asyncio.wait_for(app.async_get_variable("iterm2Version"), timeout=10)

    try:
        await asyncio.gather(tracker.run(), reap_terminated(), iterm_heartbeat())
    finally:
        await mirrors.stop_all()
        await server.stop()


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dev", action="store_true", help="bind 127.0.0.1 instead of the configured host"
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        cfg = config.load()
    except config.ConfigError as e:
        log.error("config: %s", e)
        sys.exit(1)
    host = "127.0.0.1" if args.dev else cfg.host
    try:
        asyncio.run(_run_connected(cfg, host))
    except Exception as e:
        # launchd KeepAlive restarts us; dying on a broken iTerm2 link is the
        # reconnect strategy
        log.error("exiting: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    run()
