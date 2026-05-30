"""从 Flow 页面 __NEXT_DATA__ 读取会话 access_token。"""

from __future__ import annotations

import logging

from playwright.async_api import Page

from src.browser.constants import NEXT_DATA_TIMEOUT_MS

logger = logging.getLogger(__name__)

_READ_ACCESS_TOKEN_JS = """
() => {
  const token = window.__NEXT_DATA__?.props?.pageProps?.session?.access_token;
  if (!token || typeof token !== 'string') return null;
  return token;
}
"""

_WAIT_ACCESS_TOKEN_JS = """
() => {
  const token = window.__NEXT_DATA__?.props?.pageProps?.session?.access_token;
  return typeof token === 'string' && token.length > 0;
}
"""


async def read_access_token_from_page(page: Page) -> str:
    """页面加载后从 __NEXT_DATA__.props.pageProps.session.access_token 读取 Bearer。"""
    await page.wait_for_function(
        _WAIT_ACCESS_TOKEN_JS,
        timeout=NEXT_DATA_TIMEOUT_MS,
    )
    token = await page.evaluate(_READ_ACCESS_TOKEN_JS)
    if not token:
        raise RuntimeError(
            "无法读取 __NEXT_DATA__.props.pageProps.session.access_token，"
            "请确认 Cookie 有效且项目页已登录"
        )
    logger.debug("Read access_token from __NEXT_DATA__ (length=%d)", len(token))
    return token
