import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable


def read_startup_config() -> dict:
    config_path = PROJECT_ROOT / "data" / ".config.yaml"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        example_path = PROJECT_ROOT / "config.example.yaml"
        if example_path.exists():
            shutil.copyfile(example_path, config_path)
            print("已创建 data/.config.yaml，请在正式使用前填写私有配置。")
        else:
            config_path.write_text("{}\n", encoding="utf-8")
    with config_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def start_process(command: list[str], name: str) -> subprocess.Popen:
    print(f"启动{name}：{' '.join(command)}")
    return subprocess.Popen(command, cwd=PROJECT_ROOT)


async def monitor_processes(processes: list[tuple[str, subprocess.Popen]]):
    while True:
        await asyncio.sleep(1)

        for name, process in processes:
            return_code = process.poll()
            if return_code is not None:
                raise RuntimeError(
                    f"{name}已退出，退出码：{return_code}"
                )


def stop_processes(processes: list[tuple[str, subprocess.Popen]]):
    for name, process in reversed(processes):
        if process.poll() is None:
            print(f"停止{name}")
            process.terminate()

    for _, process in processes:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


async def main():
    config = read_startup_config()
    plugins_config = config.get("plugins", {})
    remote_config = plugins_config.get("remote_api", {})
    api_host = str(remote_config.get("host", "127.0.0.1"))
    api_port = str(remote_config.get("port", 8010))

    processes = []

    try:
        processes.append(
            (
                "Desk Agent",
                start_process([PYTHON, "app.py"], "Desk Agent"),
            )
        )
        processes.append(
            (
                "远程 API",
                start_process(
                    [
                        PYTHON,
                        "-m",
                        "uvicorn",
                        "api.remote_api:app",
                        "--host",
                        api_host,
                        "--port",
                        api_port,
                    ],
                    "远程 API",
                ),
            )
        )

        feishu_config = plugins_config.get("feishu", {})
        if feishu_config.get("enabled", True):
            processes.append(
                (
                    "飞书机器人",
                    start_process(
                        [PYTHON, "-m", "api.feishu_bot"],
                        "飞书机器人",
                    ),
                )
            )

        print("Desk Agent 全部服务已启动，按 Ctrl+C 停止")
        await monitor_processes(processes)

    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError as error:
        print(f"启动失败：{error}", file=sys.stderr)
        stop_processes([])
        raise SystemExit(1)
