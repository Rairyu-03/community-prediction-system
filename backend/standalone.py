from __future__ import annotations

from datetime import datetime
import ctypes
import hashlib
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
from threading import Thread
import time
import traceback
from urllib.parse import urljoin
from urllib.request import urlopen
import webbrowser


APP_FOLDER = "CommunityPredictionSystem"
DEFAULT_PORT = 8765


def _show_message(title: str, message: str, *, error: bool = False) -> None:
    """Show a native dialog even when the console closes immediately."""
    try:
        icon = 0x10 if error else 0x40
        ctypes.windll.user32.MessageBoxW(None, message, title, icon)
    except Exception:
        print(f"{title}: {message}")


def _configure_storage() -> Path:
    frozen = bool(getattr(sys, "frozen", False))
    install_root = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parents[1]
    local_app_data = os.environ.get("LOCALAPPDATA")
    default_root = Path(local_app_data) / APP_FOLDER if local_app_data else Path.home() / "AppData" / "Local" / APP_FOLDER
    data_root = Path(os.environ.get("COMMUNITY_DATA_ROOT", default_root if frozen else install_root / "data")).resolve()
    legacy_root = install_root / "data"
    try:
        if frozen and legacy_root.is_dir() and not data_root.exists():
            shutil.copytree(legacy_root, data_root)
        data_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Some managed Windows profiles deny writes to LocalAppData.
        data_root = Path(tempfile.gettempdir()) / APP_FOLDER
        data_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(data_root / 'community_prediction.db').as_posix()}")
    os.environ.setdefault("PROJECTS_ROOT", str(data_root / "projects"))
    return data_root


def _configure_logging(data_root: Path) -> Path:
    log_root = data_root / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"startup-{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
        force=True,
    )
    return log_path


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.3)
        return connection.connect_ex((host, port)) != 0


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def _bundle_build_id() -> str:
    index_path = _bundle_root() / "frontend" / "dist" / "index.html"
    return hashlib.sha256(index_path.read_bytes()).hexdigest()[:12]


def _is_running_instance(host: str, port: int, build_id: str) -> bool:
    try:
        with urlopen(f"http://{host}:{port}/api/health", timeout=0.8) as response:
            body = json.loads(response.read().decode("utf-8"))
            return (
                response.status == 200
                and body.get("service") == "community-prediction"
                and body.get("buildId") == build_id
            )
    except Exception:
        return False


def _choose_port(host: str, requested_port: int, build_id: str) -> tuple[int, bool]:
    if _port_available(host, requested_port):
        return requested_port, False
    if _is_running_instance(host, requested_port, build_id):
        return requested_port, True
    for port in range(requested_port + 1, requested_port + 51):
        if _port_available(host, port):
            return port, False
    raise RuntimeError(f"端口 {requested_port}—{requested_port + 50} 均不可用，请关闭占用本机端口的程序后重试。")


def _frontend_ready(url: str) -> bool:
    """Confirm both the HTML shell and its JavaScript entry are available."""
    try:
        with urlopen(f"{url}/?probe=1", timeout=2) as response:
            html = response.read().decode("utf-8")
        match = re.search(r'<script[^>]+src=["\']([^"\']+\.js)["\']', html, re.IGNORECASE)
        if not match:
            return False
        asset_url = urljoin(f"{url}/", match.group(1))
        with urlopen(asset_url, timeout=3) as response:
            return response.status == 200 and len(response.read(256)) > 0
    except Exception:
        return False


def _open_browser_when_ready(url: str, browser_url: str, log_path: Path) -> None:
    """Wait for both the API and frontend bundle before opening the browser."""
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url}/api/health", timeout=1) as response:
                if response.status == 200 and _frontend_ready(url):
                    logging.info("API 与前端资源均已就绪；打开浏览器：%s", browser_url)
                    if not webbrowser.open(browser_url):
                        logging.warning("系统已启动，但未找到默认浏览器。请手动访问 %s", url)
                        _show_message("系统已启动", f"未能自动打开浏览器，请手动访问：\n{browser_url}\n\n启动日志：\n{log_path}")
                    return
        except Exception:
            time.sleep(0.35)
    logging.error("服务在90秒内未就绪：%s", url)
    _show_message("系统启动超时", f"服务在90秒内未就绪。请查看启动日志：\n{log_path}", error=True)


def _validate_bundle() -> None:
    bundle_root = _bundle_root()
    if not (bundle_root / "frontend" / "dist" / "index.html").exists():
        raise RuntimeError("程序包缺少前端资源，请重新下载完整安装包。")


def run() -> None:
    data_root = _configure_storage()
    log_path = _configure_logging(data_root)
    logging.info("应用启动；版本=0.1.0；可执行文件=%s；数据目录=%s", sys.executable, data_root)
    _validate_bundle()
    build_id = _bundle_build_id()
    os.environ["COMMUNITY_BUILD_ID"] = build_id
    logging.info("前端构建标识=%s", build_id)

    host = "127.0.0.1"
    try:
        requested_port = int(os.environ.get("COMMUNITY_PORT", str(DEFAULT_PORT)))
    except ValueError as exc:
        raise RuntimeError("COMMUNITY_PORT 必须是有效端口号。") from exc
    if not 1 <= requested_port <= 65535:
        raise RuntimeError("COMMUNITY_PORT 必须在1—65535之间。")
    port, existing_instance = _choose_port(host, requested_port, build_id)
    url = f"http://{host}:{port}"
    browser_url = f"{url}/?build={build_id}"
    if existing_instance:
        logging.info("检测到同版本系统已经运行，直接打开：%s", browser_url)
        if os.environ.get("COMMUNITY_NO_BROWSER") != "1":
            webbrowser.open(browser_url)
        return
    if port != requested_port:
        logging.warning("端口%s已被其他程序占用，自动改用端口%s。", requested_port, port)
    logging.info("服务监听地址=%s；数据目录=%s", url, data_root)

    import uvicorn
    from app.main import app

    print("完整社区设施需求预测与动态匹配系统正在启动……")
    print(f"访问地址：{url}")
    print(f"数据目录：{data_root}")
    print(f"启动日志：{log_path}")
    print("关闭本窗口即可停止系统。")
    if os.environ.get("COMMUNITY_NO_BROWSER") != "1":
        Thread(target=_open_browser_when_ready, args=(url, browser_url, log_path), daemon=True).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    multiprocessing.freeze_support()
    try:
        run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        try:
            data_root = _configure_storage()
            log_path = _configure_logging(data_root)
            logging.critical("启动失败\n%s", traceback.format_exc())
        except Exception:
            log_path = Path(tempfile.gettempdir()) / "CommunityPredictionSystem-startup-error.log"
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
        _show_message(
            "完整社区预测系统启动失败",
            f"{exc}\n\n诊断日志：\n{log_path}\n\n请将该日志发给技术支持。",
            error=True,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
