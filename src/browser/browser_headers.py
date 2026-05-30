"""从真实 Chrome 网络请求捕获 Flow API 所需的 x-browser-* / x-client-data 头。"""

from __future__ import annotations

import base64
import threading
import hashlib
import logging
import platform
import time
from datetime import datetime

from playwright.async_api import BrowserContext, Page, Request

from src.browser.constants import HEADER_CAPTURE_TIMEOUT

logger = logging.getLogger(__name__)

FLOW_BROWSER_HEADER_KEYS = frozenset(
    {
        "x-browser-channel",
        "x-browser-copyright",
        "x-browser-validation",
        "x-browser-year",
        "x-client-data",
    }
)

_GOOGLE_URL_MARKERS = (
    "google.com",
    "googleapis.com",
    "labs.google",
    "gstatic.com",
    "googleusercontent.com",
)

# Chrome x-browser-validation: base64(sha1(api_key + user_agent))
_PLATFORM_API_KEYS: dict[str, str] = {
    "Windows": "ActWl2RdyFxJUMCuTw2fW7Trksygb5lf",
    "Darwin": "E5EB6BC725D7783B9E487CBD401A88F",
    "Linux": "AIMKHL0JB0FNu77Py7d6Q9S3TvJL8HGU",
}


def compute_x_browser_validation(user_agent: str) -> str:
    system = platform.system()
    api_key = _PLATFORM_API_KEYS.get(system, _PLATFORM_API_KEYS["Windows"])
    digest = hashlib.sha1(f"{api_key}{user_agent}".encode()).digest()
    return base64.b64encode(digest).decode()


def default_static_browser_headers() -> dict[str, str]:
    year = str(datetime.now().year)
    return {
        "x-browser-channel": "stable",
        "x-browser-copyright": f"Copyright {year} Google LLC. All Rights Reserved.",
        "x-browser-year": year,
    }


class BrowserHeaderStore:
    """累积 Context 内所有页面发往 Google 的请求头。"""

    def __init__(self) -> None:
        self._headers: dict[str, str] = {}
        self._lock = threading.Lock()

    def get_headers(self) -> dict[str, str]:
        return dict(self._headers)

    def has_validation(self) -> bool:
        return bool(self._headers.get("x-browser-validation"))

    def has_client_data(self) -> bool:
        return bool(self._headers.get("x-client-data"))

    def is_ready(self) -> bool:
        if not self.has_validation():
            return False
        return self.has_client_data()

    def update_from_request(self, request: Request) -> None:
        url = request.url.lower()
        if not any(marker in url for marker in _GOOGLE_URL_MARKERS):
            return

        try:
            raw_headers = request.headers
        except Exception:
            return

        with self._lock:
            for name, value in raw_headers.items():
                key = name.lower()
                if key in FLOW_BROWSER_HEADER_KEYS and value:
                    self._headers[key] = value

    async def wait_until_ready(self, timeout: float | None = None) -> None:
        import asyncio

        deadline = time.monotonic() + (
            timeout if timeout is not None else HEADER_CAPTURE_TIMEOUT
        )
        while time.monotonic() < deadline:
            if self.is_ready():
                return
            await asyncio.sleep(0.15)


def _on_context_request(store: BrowserHeaderStore):
    def handler(request: Request) -> None:
        store.update_from_request(request)

    return handler


def attach_header_capture(context: BrowserContext, store: BrowserHeaderStore) -> None:
    context.on("request", _on_context_request(store))
    logger.info("Browser header capture attached on context")


async def resolve_flow_api_headers(page: Page, store: BrowserHeaderStore) -> dict[str, str]:
    """
    解析 Flow API 附加头：
    1. 等待 Context 内 Google 请求捕获（预热页通常已产生）
    2. 按 UA 计算缺失的 x-browser-validation
    3. 补全 channel / copyright / year
    """
    await store.wait_until_ready()

    headers = store.get_headers()

    for key, value in default_static_browser_headers().items():
        headers.setdefault(key, value)

    if "x-browser-validation" not in headers:
        user_agent = await page.evaluate("() => navigator.userAgent || ''")
        if user_agent:
            headers["x-browser-validation"] = compute_x_browser_validation(user_agent)
            logger.info("Computed x-browser-validation from User-Agent")

    missing = [k for k in FLOW_BROWSER_HEADER_KEYS if k not in headers]
    if missing:
        logger.warning("Flow API headers still missing: %s", missing)
    else:
        logger.debug("Flow API browser headers fully resolved")

    return headers
