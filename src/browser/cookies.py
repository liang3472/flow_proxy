"""在访问 labs.google 前注入 / 请求后清理 NextAuth 等会话状态。"""

from __future__ import annotations

import logging

from playwright.async_api import BrowserContext, Page

from src.browser.constants import (
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SAME_SITE,
    SESSION_COOKIE_URL,
)

logger = logging.getLogger(__name__)


def _is_labs_domain(domain: str) -> bool:
    d = (domain or "").lstrip(".").lower()
    return d == "labs.google" or d.endswith(".labs.google")


def _should_remove_cookie(_name: str, domain: str) -> bool:
    return _is_labs_domain(domain)


async def _collect_labs_cookies(context: BrowserContext) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    collected: list[dict] = []

    for url in (
        SESSION_COOKIE_URL,
        "https://labs.google",
        "https://labs.google/fx",
    ):
        try:
            batch = await context.cookies(url)
        except Exception:
            continue
        for cookie in batch:
            name = cookie.get("name") or ""
            domain = cookie.get("domain") or ""
            path = cookie.get("path") or "/"
            key = (name, domain, path)
            if key in seen:
                continue
            seen.add(key)
            collected.append(cookie)
    return collected


async def clear_labs_google_session(
    context: BrowserContext,
    page: Page | None = None,
) -> None:
    """清理 labs.google 会话 Cookie 与页面 storage（每次请求固定执行）。"""
    removed = 0
    for cookie in await _collect_labs_cookies(context):
        name = cookie.get("name") or ""
        domain = cookie.get("domain") or ""
        if not _should_remove_cookie(name, domain):
            continue
        try:
            await context.clear_cookies(
                name=name,
                domain=domain,
                path=cookie.get("path") or "/",
            )
            removed += 1
        except Exception as exc:
            logger.debug("clear cookie %s failed: %s", name, exc)

    if page and not page.is_closed():
        try:
            await page.evaluate(
                """
                () => {
                  try { localStorage.clear(); } catch (_) {}
                  try { sessionStorage.clear(); } catch (_) {}
                }
                """
            )
        except Exception as exc:
            logger.debug("clear page storage failed: %s", exc)

    if removed:
        logger.info("Cleared %d labs.google cookie(s)", removed)


async def inject_session_cookie(context: BrowserContext, token: str) -> None:
    """注入 __Secure-next-auth.session-token（在 page.goto 项目页之前调用）。"""
    if not token or not token.strip():
        raise ValueError("session cookie value is empty")

    await clear_labs_google_session(context)

    cookie = {
        "name": SESSION_COOKIE_NAME,
        "value": token.strip(),
        "url": SESSION_COOKIE_URL,
        "secure": True,
        "httpOnly": True,
        "sameSite": SESSION_COOKIE_SAME_SITE,
    }

    await context.add_cookies([cookie])
    logger.info("Injected cookie %s for %s", SESSION_COOKIE_NAME, SESSION_COOKIE_URL)
