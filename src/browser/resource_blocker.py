"""拦截非必要资源，加快 labs.google / Flow 页面加载。"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Route

logger = logging.getLogger(__name__)

# 打码与 API 所需域名（子串匹配 host）
_ESSENTIAL_HOST_PARTS = (
    "labs.google",
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "googleusercontent.com",
    "recaptcha.net",
    "googlesyndication.com",
)

# 按 Playwright resource_type 直接丢弃
_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})

# 可选：样式表（Flow 打码不依赖页面样式）
_STYLESHEET_TYPE = "stylesheet"

# 追踪 / 广告 / 无关第三方
_TRACKER_URL_PARTS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googleadservices.com",
    "facebook.com",
    "facebook.net",
    "hotjar.com",
    "segment.io",
    "segment.com",
    "sentry.io",
    "amplitude.com",
    "mixpanel.com",
    "clarity.ms",
    "optimizely.com",
    "intercom.io",
    "fullstory.com",
    "newrelic.com",
    "nr-data.net",
    "adservice.google",
    "pagead2.googlesyndication.com",
)

# 大体积媒体 CDN（缩略图/预览，与打码无关）
_MEDIA_CDN_PARTS = (
    "storage.googleapis.com/ai-sandbox",
    "lh3.googleusercontent.com",
    "ytimg.com",
    "youtube.com",
    "youtu.be",
    "vimeo.com",
)

# 常见静态后缀（resource_type 不可靠时的兜底）
_HEAVY_SUFFIXES = (
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".avi",
    ".mov",
    ".gif",
    ".webp",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_essential_host(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    return any(part in host for part in _ESSENTIAL_HOST_PARTS)


def _url_contains(url: str, parts: tuple[str, ...]) -> bool:
    lower = url.lower()
    return any(p in lower for p in parts)


def should_block_request(resource_type: str, url: str) -> bool:
    rtype = (resource_type or "").lower()

    if rtype in _BLOCKED_RESOURCE_TYPES:
        return True

    if rtype == _STYLESHEET_TYPE:
        return True

    # 预加载 / 预连接对打码无益
    if rtype in ("prefetch", "preload"):
        return True

    if _url_contains(url, _TRACKER_URL_PARTS):
        return True

    if _url_contains(url, _MEDIA_CDN_PARTS):
        return True

    # 非核心域名的 websocket / manifest / 其它杂项
    if rtype in ("websocket", "manifest", "other", "texttrack"):
        if not _is_essential_host(url):
            return True

    # 非 Google 体系的 script 常是第三方挂件
    if rtype == "script" and not _is_essential_host(url):
        return True

    # 兜底：带媒体后缀且非 reCAPTCHA 相关
    path = url.lower().split("?", 1)[0]
    if any(path.endswith(sfx) for sfx in _HEAVY_SUFFIXES):
        if any(k in url.lower() for k in ("recaptcha", "enterprise.js")):
            return False
        if rtype not in ("document", "script", "xhr", "fetch"):
            return True

    return False


async def _route_handler(route: Route) -> None:
    request = route.request
    try:
        if should_block_request(request.resource_type, request.url):
            await route.abort()
            return
        await route.continue_()
    except Exception as exc:
        logger.debug("route handler error: %s", exc)
        try:
            await route.continue_()
        except Exception:
            pass


async def attach_resource_blocker(context: BrowserContext) -> None:
    """在 BrowserContext 上注册全局路由（预热页与工作标签页均生效）。"""
    await context.route("**/*", _route_handler)
    logger.info("Resource blocker enabled (images/media/fonts+css, trackers=True)")


def chromium_speed_args() -> list[str]:
    """Chromium 启动参数：减少后台开销。"""
    return [
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--disable-features=Translate,MediaRouter",
        "--blink-settings=imagesEnabled=false",
    ]
