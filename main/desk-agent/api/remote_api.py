import asyncio
import logging

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from api.config import get_config_value, get_remote_api_config
from api.desk_agent_client import send_agent_command


logger = logging.getLogger("desk-agent.remote-api")

app = FastAPI(title="Desk Agent Remote API")

REMOTE_API_CONFIG = get_remote_api_config()
REMOTE_API_TOKEN = get_config_value(
    REMOTE_API_CONFIG,
    "token",
    "DESK_AGENT_REMOTE_TOKEN",
)


class CommandRequest(BaseModel):
    command: str
    client_id: str = "remote-api-default"


class CommandResponse(BaseModel):
    accepted: bool
    message: str
    client_id: str


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent_connected": True,
    }


@app.post("/command", response_model=CommandResponse)
async def command(
    request: CommandRequest,
    authorization: str | None = Header(default=None),
):
    if not REMOTE_API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="remote API token is not configured",
        )

    expected = f"Bearer {REMOTE_API_TOKEN}"

    if authorization != expected:
        raise HTTPException(
            status_code=401,
            detail="invalid token",
        )

    command_text = request.command.strip()
    client_id = request.client_id.strip()

    if not command_text:
        raise HTTPException(
            status_code=400,
            detail="command cannot be empty",
        )

    if not client_id:
        raise HTTPException(
            status_code=400,
            detail="client_id cannot be empty",
        )

    if len(client_id) > 100:
        raise HTTPException(
            status_code=400,
            detail="client_id is too long",
        )

    logger.info(
        "收到远程指令: client_id=%s, command=%s",
        client_id,
        command_text,
    )

    try:
        # send_agent_command 使用同步 WebSocket。
        # 放到线程中执行，避免阻塞 FastAPI 事件循环。
        result = await asyncio.to_thread(
            send_agent_command,
            command_text,
            client_id,
        )

    except TimeoutError as error:
        logger.warning(
            "Agent 执行超时: client_id=%s, error=%s",
            client_id,
            error,
        )
        raise HTTPException(
            status_code=504,
            detail="Desk Agent 执行超时",
        ) from error

    except (ConnectionError, OSError) as error:
        logger.warning(
            "无法连接 Desk Agent: client_id=%s, error=%s",
            client_id,
            error,
        )
        raise HTTPException(
            status_code=503,
            detail="Desk Agent 当前不可用，请确认 Agent 已启动",
        ) from error

    except Exception as error:
        logger.exception(
            "Agent 执行失败: client_id=%s",
            client_id,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Desk Agent 执行失败: {error}",
        ) from error

    return CommandResponse(
        accepted=True,
        message=result,
        client_id=client_id,
    )