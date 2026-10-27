"""Exercise the WebSocket bridge with synthetic data and no iTerm2 connection."""

import asyncio
import json
import secrets

from websockets.asyncio.client import connect

from limpet.server import BridgeServer


async def main():
    async def subscribe(sid):
        await server.publish_grid(sid, 80, 24)
        await server.publish_screen(sid, "synthetic terminal", reset=True)

    async def input_text(sid, text):
        print(f"input: {text!r}")

    async def unused(*args):
        pass

    token = secrets.token_hex(32)
    server = BridgeServer(token, "synthetic", subscribe, unused, input_text, unused, unused)
    port = await server.start("127.0.0.1", 0)
    try:
        await server.publish_sessions([{"id": "demo"}])
        async with connect(
            f"ws://127.0.0.1:{port}", additional_headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            print(f"protocol: {json.loads(await ws.recv())['proto']}")
            print(f"sessions: {json.loads(await ws.recv())['list'][0]['id']}")
            await ws.send(json.dumps({"type": "subscribe", "session": "demo"}))
            grid = json.loads(await ws.recv())
            print(f"grid: {grid['cols']}x{grid['rows']}")
            print(f"screen: {json.loads(await ws.recv())['ansi']}")
            await ws.send(json.dumps({"type": "input", "session": "demo", "text": "hello\n"}))
            await ws.send(json.dumps({"type": "ping"}))
            print(f"ping: {json.loads(await ws.recv())['type']}")
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=5))
