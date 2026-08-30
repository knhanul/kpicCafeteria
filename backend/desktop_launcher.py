from __future__ import annotations

import ctypes
import os
import threading
import time
import urllib.error
import urllib.request

from app.desktop_runtime import configure_desktop_environment, reserve_local_port


_MUTEX_NAME = "Local\\KPICCafeteriaDesktop"
_ERROR_ALREADY_EXISTS = 183


class DesktopServer(threading.Thread):
    def __init__(self, port: int):
        super().__init__(name="cafeteria-api", daemon=True)
        import uvicorn
        from app.main import app

        self.server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info", access_log=False)
        )

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True
        self.join(timeout=10)


def wait_until_ready(url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"PC 앱 서버를 시작하지 못했습니다: {last_error}")


def acquire_single_instance_mutex():
    if os.name != "nt":
        raise RuntimeError("PC 버전은 Windows에서만 실행할 수 있습니다.")
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        raise ctypes.WinError()
    if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        raise RuntimeError("구내식당 관리 PC 버전이 이미 실행 중입니다.")
    return handle


def main() -> None:
    mutex = acquire_single_instance_mutex()
    server: DesktopServer | None = None
    try:
        configure_desktop_environment()
        port = reserve_local_port()
        base_url = f"http://127.0.0.1:{port}"
        server = DesktopServer(port)
        server.start()
        wait_until_ready(f"{base_url}/health")

        import webview

        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.create_window(
            "구내식당 관리",
            base_url,
            width=1440,
            height=900,
            min_size=(1180, 720),
            text_select=True,
        )
        webview.start(gui="edgechromium", private_mode=False)
    finally:
        if server:
            server.stop()
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
