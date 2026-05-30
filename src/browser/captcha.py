import asyncio
import logging

from playwright.async_api import Page

from src.config import settings
from src.log_util import format_token_for_log

logger = logging.getLogger(__name__)


async def solve_recaptcha_on_page(
    page: Page,
    *,
    site_key: str | None = None,
    action: str | None = None,
) -> str:
    """在当前页面执行 grecaptcha.enterprise.execute 并返回 token。"""
    key = site_key or settings.recaptcha_site_key
    act = action or settings.recaptcha_action_image
    timeout_s = settings.browser_captcha_timeout

    await page.wait_for_function(
        "() => typeof grecaptcha !== 'undefined' && "
        "typeof grecaptcha.enterprise !== 'undefined' && "
        "typeof grecaptcha.enterprise.execute === 'function'",
        timeout=settings.captcha_timeout_ms,
    )

    token = await asyncio.wait_for(
        page.evaluate(
            """
            async ({ siteKey, actionName, timeoutMs }) => {
              return await new Promise((resolve, reject) => {
                const timer = setTimeout(
                  () => reject(new Error('recaptcha execute timeout')),
                  timeoutMs,
                );
                grecaptcha.enterprise
                  .execute(siteKey, { action: actionName })
                  .then((t) => {
                    clearTimeout(timer);
                    resolve(t);
                  })
                  .catch((e) => {
                    clearTimeout(timer);
                    reject(e);
                  });
              });
            }
            """,
            {
                "siteKey": key,
                "actionName": act,
                "timeoutMs": timeout_s * 1000,
            },
        ),
        timeout=timeout_s + 5,
    )

    if not token:
        raise RuntimeError("reCAPTCHA returned empty token")

    logger.info("打码返回 recaptcha_token: %s", format_token_for_log(token))

    settle = settings.browser_recaptcha_settle_seconds
    if settle > 0:
        await asyncio.sleep(settle)

    return token
