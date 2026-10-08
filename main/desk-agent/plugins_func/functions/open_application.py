#
# 用户说出的应用名先被归一化成标准 key，再用它去硬编码白名单或配置文件里**精确查表
# **拿到真实命令，最后以 `shell=False` 的列表形式交给 `subprocess.Popen` 
# 启动——用户输入永远只是"查表的钥匙"，而不是"被执行的命令"。
#在白名单就直接执行，不在白名单需要查配置

import os
import platform
import subprocess
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import (
    register_function,
    ToolType,
    ActionResponse,
    Action,
)

if TYPE_CHECKING:
    from core.connection import ConnectionHandler


TAG = __name__
logger = setup_logging()


OPEN_APPLICATION_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "open_application",
        "description": (
            "打开Windows桌面应用程序。"
            "当用户明确要求打开记事本、计算器、文件管理器、命令行、PowerShell、QQ、WPS或Word时调用。"
            "目前只允许打开系统白名单应用以及配置文件中明确配置路径的QQ、WPS和Word。"
            "不要尝试执行任意命令，也不要打开未配置的程序。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "application": {
                    "type": "string",
                    "description": (
                        "要打开的应用名称，例如：记事本、计算器、"
                        "文件管理器、命令行、PowerShell、QQ、WPS"
                    ),
                }
            },
            "required": ["application"],
        },
    },
}


# 用户说法映射为统一名称
APPLICATION_ALIASES = {
    "记事本": "notepad",
    "notepad": "notepad",

    "计算器": "calculator",
    "calc": "calculator",
    "calculator": "calculator",

    "文件管理器": "explorer",
    "资源管理器": "explorer",
    "explorer": "explorer",

    "命令行": "cmd",
    "cmd": "cmd",
    "终端": "cmd",

    "powershell": "powershell",
    "PowerShell": "powershell",

    "qq": "qq",
    "腾讯qq": "qq",

    "wps": "wps",
    "wpsoffice": "wps",
    "wps office": "wps",

    "word": "word",
    "microsoftword": "word",
    "微软word": "word",
    "office": "word",
}


# 系统自带程序可以直接通过程序名启动
SYSTEM_APPLICATIONS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
}


def normalize_application_name(application: str) -> str:
    """统一应用名称格式。"""
    value = str(application or "").strip().lower()
    value = value.replace(" ", "")
    return APPLICATION_ALIASES.get(value, value)


def get_application_command(conn, application: str):
    """根据配置和白名单获取启动命令。"""
    app_name = normalize_application_name(application)

    # 先处理系统白名单应用
    if app_name in SYSTEM_APPLICATIONS:
        return SYSTEM_APPLICATIONS[app_name], None

    # QQ、WPS等第三方软件必须从配置中读取路径
    application_config = (
        conn.config.get("plugins", {})
        .get("open_application", {})
    )

    configured_paths = application_config.get("paths", {})
    configured_path = configured_paths.get(app_name)

    if not configured_path:
        return None, (
            f"{application}还没有配置程序路径。"
            f"请在data/.config.yaml的plugins.open_application.paths."
            f"{app_name}中填写exe文件路径。"
        )

    program_path = os.path.expandvars(
        os.path.expanduser(str(configured_path))
    )

    if not os.path.isfile(program_path):
        return None, f"找不到{application}的程序文件：{program_path}"

    return [program_path], None


@register_function(
    "open_application",
    OPEN_APPLICATION_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
def open_application(
    conn: "ConnectionHandler",
    application: str,
):
    """打开Windows桌面应用。"""
    if platform.system() != "Windows":
        message = "当前打开应用功能只支持Windows系统。"
        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    command, error_message = get_application_command(conn, application)

    if error_message:
        logger.bind(tag=TAG).warning(error_message)
        return ActionResponse(
            action=Action.RESPONSE,
            result=error_message,
            response=error_message,
        )

    try:
        # 不使用shell=True，避免执行任意命令
        subprocess.Popen(command, shell=False)

        message = f"已打开{application}"
        logger.bind(tag=TAG).info(
            f"打开应用成功: {application}, command={command}"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except Exception as error:
        logger.bind(tag=TAG).error(
            f"打开应用失败: {application}, error={error}"
        )

        message = f"打开{application}失败：{error}"
        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
