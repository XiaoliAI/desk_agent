import asyncio
import signal
import sys
import uuid

from config.logger import setup_logging
from config.settings import load_config
from core.utils.gc_manager import get_gc_manager
from core.utils.util import check_ffmpeg_installed, get_local_ip, validate_mcp_endpoint
from core.websocket_server import WebSocketServer


TAG = __name__
logger = setup_logging()


async def wait_for_exit() -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
    else:
        try:
            await asyncio.Future()
        except KeyboardInterrupt:
            pass


async def main() -> None:
    check_ffmpeg_installed()
    config = await load_config()

    auth_key = config.get("server", {}).get("auth_key", "")
    if not auth_key or "your" in auth_key.lower() or "你的" in auth_key:
        auth_key = uuid.uuid4().hex
    config["server"]["auth_key"] = auth_key

    mcp_endpoint = config.get("mcp_endpoint")
    if mcp_endpoint and "你的" not in mcp_endpoint:
        if validate_mcp_endpoint(mcp_endpoint):
            logger.bind(tag=TAG).info("MCP endpoint: {}", mcp_endpoint)
            config["mcp_endpoint"] = mcp_endpoint.replace("/mcp/", "/call/")
        else:
            logger.bind(tag=TAG).warning("Invalid MCP endpoint ignored: {}", mcp_endpoint)
            config["mcp_endpoint"] = ""

    gc_manager = get_gc_manager(interval_seconds=300)
    await gc_manager.start()

    ws_server = WebSocketServer(config)
    ws_task = asyncio.create_task(ws_server.start())

    websocket_port = int(config.get("server", {}).get("port", 8000))
    logger.bind(tag=TAG).info(
        "Desk Agent WebSocket: ws://{}:{}/xiaozhi/v1/",
        get_local_ip(),
        websocket_port,
    )
    logger.bind(tag=TAG).info(
        "Digital human UI can connect directly to ws://127.0.0.1:{}/xiaozhi/v1/",
        websocket_port,
    )

    try:
        await wait_for_exit()
    except asyncio.CancelledError:
        logger.bind(tag=TAG).info("Desk Agent is shutting down")
    finally:
        await gc_manager.stop()
        ws_task.cancel()
        await asyncio.wait([ws_task], timeout=3.0, return_when=asyncio.ALL_COMPLETED)
        logger.bind(tag=TAG).info("Desk Agent stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Desk Agent stopped")
