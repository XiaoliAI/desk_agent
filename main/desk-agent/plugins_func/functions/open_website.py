#open_website 是"打开网页"插件：
# 先把用户口语（"百度"）和网址归一化并做协议/格式安全校验
# （只允许 http/https，拦截 file/javascript、用户名密码钓鱼），
# 再按 default（系统默认浏览器）或配置的浏览器路径，
# 用 shell=False 的 subprocess.Popen 打开——整体思路和 open_application 一致，
# 但安全核心从"白名单精确匹配"换成了"URL 协议校验"。


import os
import platform
import subprocess
import webbrowser
from typing import TYPE_CHECKING
from urllib.parse import urlparse

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


OPEN_WEBSITE_FUNCTION_DESC = {
    "type": "function",
    "function": {
        "name": "open_website",
        "description": (
            "打开网页。"
            "当用户要求打开百度、视频网站、GitHub或指定网址时调用。"
            "如果用户只说网站名称，需要自动补全为对应的网址。"
            "默认使用系统默认浏览器，也可以根据用户要求使用Edge、Chrome或Firefox。"
            "只允许打开http和https网页。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "要打开的网址，例如 https://www.baidu.com。"
                        "如果用户说百度、B站、GitHub等，应转换为对应网址。"
                    ),
                },
                "browser": {
                    "type": "string",
                    "description": (
                        "浏览器名称，可选值：default、edge、chrome、firefox。"
                        "不提供时使用系统默认浏览器。"
                    ),
                },
            },
            "required": ["url"],
        },
    },
}


WEBSITE_ALIASES = {
    "百度": "https://www.baidu.com",
    "百度一下": "https://www.baidu.com",
    "百度浏览器": "https://www.baidu.com",
    "百度网页": "https://www.baidu.com",
    "b站": "https://www.bilibili.com",
    "哔哩哔哩": "https://www.bilibili.com",
    " bilibili": "https://www.bilibili.com",
    "github": "https://github.com",
    "git hub": "https://github.com",
    "谷歌": "https://www.google.com",
    "google": "https://www.google.com",
    "淘宝": "https://www.taobao.com",
    "京东": "https://www.jd.com",
    "知乎": "https://www.zhihu.com",
}


BROWSER_ALIASES = {
    "默认": "default",
    "默认浏览器": "default",
    "系统默认": "default",
    "default": "default",
    "edge": "edge",
    "微软edge": "edge",
    "Microsoft Edge": "edge",
    "chrome": "chrome",
    "谷歌浏览器": "chrome",
    "firefox": "firefox",
    "火狐": "firefox",
}


def normalize_browser(browser: str | None) -> str:
    value = str(browser or "default").strip().lower()
    return BROWSER_ALIASES.get(value, value)


def normalize_url(url: str):
    """校验并规范化用户输入的网址。"""
    value = str(url or "").strip()

    if not value:
        return None, "网址不能为空"

    alias_key = value.lower().replace(" ", "")
    for name, alias_url in WEBSITE_ALIASES.items():
        if alias_key == name.lower().replace(" ", ""):
            value = alias_url
            break

    # 先检查显式协议，拦截 file、javascript 等危险协议
    initial_parsed = urlparse(value)
    if initial_parsed.scheme:
        if initial_parsed.scheme.lower() not in {"http", "https"}:
            return None, "只允许打开http或https网页"

    if " " in value:
        return None, "网址中不能包含空格"

    if not initial_parsed.scheme:
        value = "https://" + value

    parsed = urlparse(value)

    if parsed.scheme.lower() not in {"http", "https"}:
        return None, "只允许打开http或https网页"

    if not parsed.netloc:
        return None, "网址格式不正确"

    # 不允许打开携带用户名和密码的地址
    if parsed.username or parsed.password:
        return None, "不允许打开包含用户名或密码的网址"

    try:
        hostname = parsed.hostname
    except ValueError:
        return None, "网址域名格式不正确"

    if not hostname:
        return None, "网址缺少域名"

    return value, None


def get_website_config(conn):
    return (
        conn.config
        .get("plugins", {})
        .get("open_website", {})
    )


def open_with_browser(conn, url: str, browser: str):
    """使用系统默认浏览器或配置过的浏览器打开网页。"""
    browser = normalize_browser(browser)
    website_config = get_website_config(conn)

    if browser == "default":
        if platform.system() == "Windows":
            os.startfile(url)
        else:
            webbrowser.open(url)
        return

    browsers = website_config.get("browsers", {})
    browser_path = browsers.get(browser)

    if not browser_path:
        raise RuntimeError(
            f"{browser}尚未配置程序路径，请在data/.config.yaml中配置"
        )

    browser_path = os.path.expandvars(
        os.path.expanduser(str(browser_path))
    )

    if not os.path.isfile(browser_path):
        raise FileNotFoundError(
            f"找不到浏览器程序：{browser_path}"
        )

    # 不使用shell=True，避免执行任意命令
    subprocess.Popen(
        [browser_path, url],
        shell=False,
    )


@register_function(
    "open_website",
    OPEN_WEBSITE_FUNCTION_DESC,
    ToolType.SYSTEM_CTL,
)
def open_website(
    conn: "ConnectionHandler",
    url: str,
    browser: str = "default",
):
    """打开指定网页。"""
    normalized_url, error_message = normalize_url(url)

    if error_message:
        logger.bind(tag=TAG).warning(error_message)
        return ActionResponse(
            action=Action.RESPONSE,
            result=error_message,
            response=error_message,
        )

    try:
        open_with_browser(conn, normalized_url, browser)

        browser_name = normalize_browser(browser)
        if browser_name == "default":
            message = f"已使用系统默认浏览器打开：{normalized_url}"
        else:
            message = f"已使用{browser_name}打开：{normalized_url}"

        logger.bind(tag=TAG).info(
            f"打开网页成功: url={normalized_url}, browser={browser_name}"
        )

        return ActionResponse(
            action=Action.RESPONSE,
            result=message,
            response=message,
        )

    except Exception as error:
        message = f"打开网页失败：{error}"
        logger.bind(tag=TAG).error(message)

        return ActionResponse(
            action=Action.ERROR,
            result=message,
            response=message,
        )
