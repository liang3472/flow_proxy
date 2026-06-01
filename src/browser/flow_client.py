import asyncio
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from src.browser.browser_headers import (
    BrowserHeaderStore,
    attach_header_capture,
    resolve_flow_api_headers,
)
from src.browser.captcha import solve_recaptcha_on_page
from src.browser.cookies import clear_labs_google_session, inject_session_cookie
from src.browser.resource_blocker import attach_resource_blocker, chromium_speed_args
from src.browser.session import read_access_token_from_page
from src.browser.constants import BROWSER_CHANNEL, GOTO_WAIT_UNTIL, PROJECT_GOTO_WAIT_UNTIL
from src.config import settings
from src.log_util import format_token_for_log
from src.models import (
    ImageGenerateRequest,
    MediaUrlRequest,
    VideoGenerateRequest,
    VideoStatusCheckRequest,
)

logger = logging.getLogger(__name__)

INJECT_RECAPTCHA_SCRIPT = """
(() => {
  if (window.__flowProxyCaptchaBridge) return;
  window.__flowProxyCaptchaBridge = true;
  const SITE_KEY = '__SITE_KEY__';
  window.addEventListener('FLOW_PROXY_GET_CAPTCHA', async (ev) => {
    const { requestId, pageAction } = ev.detail || {};
    try {
      const wait = (timeout = 10000) => new Promise((resolve, reject) => {
        const start = Date.now();
        const tick = () => {
          if (window.grecaptcha?.enterprise?.execute) return resolve();
          if (Date.now() - start > timeout) return reject(new Error('grecaptcha not available'));
          setTimeout(tick, 200);
        };
        tick();
      });
      await wait();
      const token = await window.grecaptcha.enterprise.execute(SITE_KEY, { action: pageAction });
      window.dispatchEvent(new CustomEvent('FLOW_PROXY_CAPTCHA_RESULT', {
        detail: { requestId, token },
      }));
    } catch (e) {
      window.dispatchEvent(new CustomEvent('FLOW_PROXY_CAPTCHA_RESULT', {
        detail: { requestId, error: e?.message || String(e) },
      }));
    }
  });
})();
""".replace("__SITE_KEY__", settings.recaptcha_site_key)

WEBDRIVER_HIDE_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
)


def _project_url(project_id: str) -> str:
    return settings.flow_project_url_template.format(project_id=project_id)


def _media_url_redirect_url(media_name: str) -> str:
    path = settings.flow_media_url_redirect_template.format(
        name=quote(media_name, safe="")
    )
    return f"{settings.flow_labs_origin.rstrip('/')}{path}"


def _build_request_body(req: ImageGenerateRequest, recaptcha_token: str) -> dict[str, Any]:
    session_id = f";{int(time.time() * 1000)}"
    batch_id = req.batch_id or str(uuid.uuid4())
    seed = req.seed if req.seed is not None else random.randint(1, 999_999)

    client_context = {
        "recaptchaContext": {
            "token": recaptcha_token,
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
        },
        "projectId": req.project_id,
        "tool": "PINHOLE",
        "sessionId": session_id,
    }

    request_item = {
        "clientContext": dict(client_context),
        "imageModelName": req.image_model_name,
        "imageAspectRatio": req.image_aspect_ratio,
        "structuredPrompt": {
            "parts": [{"text": req.prompt}],
        },
        "seed": seed,
        "imageInputs": req.image_inputs,
    }

    return {
        "clientContext": client_context,
        "mediaGenerationContext": {"batchId": batch_id},
        "useNewMedia": True,
        "requests": [request_item],
    }


def _build_video_request_body(req: VideoGenerateRequest, recaptcha_token: str) -> dict[str, Any]:
    session_id = f";{int(time.time() * 1000)}"
    batch_id = req.batch_id or str(uuid.uuid4())
    seed = req.seed if req.seed is not None else random.randint(1, 999_999)

    client_context = {
        "recaptchaContext": {
            "token": recaptcha_token,
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
        },
        "projectId": req.project_id,
        "tool": "PINHOLE",
        "userPaygateTier": req.user_paygate_tier,
        "sessionId": session_id,
    }

    request_item = {
        "aspectRatio": req.video_aspect_ratio,
        "textInput": {
            "structuredPrompt": {
                "parts": [{"text": req.prompt}],
            },
        },
        "videoModelKey": req.video_model_key,
        "seed": seed,
        "metadata": req.metadata,
    }

    body: dict[str, Any] = {
        "clientContext": client_context,
        "mediaGenerationContext": {
            "batchId": batch_id,
            "audioFailurePreference": req.audio_failure_preference,
        },
        "requests": [request_item],
    }
    if req.use_v2_model_config:
        body["useV2ModelConfig"] = True
    return body


def _build_video_status_request_body(req: VideoStatusCheckRequest) -> dict[str, Any]:
    return {
        "media": [
            {
                "name": item.name,
                "projectId": item.project_id or req.project_id,
            }
            for item in req.media
        ]
    }


async def _get_media_url_redirect_in_page(
    page: Page,
    *,
    url: str,
    follow_redirect: bool,
) -> dict[str, Any]:
    return await page.evaluate(
        """
        async ({ url, followRedirect }) => {
          const findHttpUrl = (payload) => {
            const stack = [payload];
            while (stack.length) {
              const cur = stack.pop();
              if (typeof cur === 'string' && /^https?:\\/\\//i.test(cur)) {
                return cur;
              }
              if (cur && typeof cur === 'object') {
                for (const v of Object.values(cur)) stack.push(v);
              }
            }
            return null;
          };

          const res = await fetch(url, {
            method: 'GET',
            credentials: 'include',
            redirect: followRedirect ? 'follow' : 'manual',
          });

          if (!followRedirect && res.status >= 300 && res.status < 400) {
            const location = res.headers.get('location');
            return {
              status: res.status,
              ok: Boolean(location),
              data: {
                url: location,
                redirect: true,
              },
            };
          }

          const contentType = res.headers.get('content-type') || '';
          let raw = null;
          if (contentType.includes('application/json')) {
            try {
              raw = await res.json();
            } catch {
              raw = null;
            }
          } else {
            const text = await res.text();
            if (text) {
              try {
                raw = JSON.parse(text);
              } catch {
                raw = text;
              }
            }
          }

          const parsedUrl = raw ? findHttpUrl(raw) : null;
          const finalUrl = parsedUrl || (res.url !== url ? res.url : null);

          return {
            status: res.status,
            ok: res.ok && Boolean(finalUrl),
            data: {
              url: finalUrl,
              redirect: Boolean(finalUrl && finalUrl !== url),
              raw,
            },
          };
        }
        """,
        {"url": url, "followRedirect": follow_redirect},
    )


async def _post_flow_api_in_page(
    page: Page,
    *,
    url: str,
    access_token: str,
    body: dict[str, Any],
    browser_headers: dict[str, str],
) -> dict[str, Any]:
    return await page.evaluate(
        """
        async ({ url, token, body, browserHeaders }) => {
          const res = await fetch(url, {
            method: 'POST',
            headers: {
              authorization: `Bearer ${token}`,
              'content-type': 'text/plain;charset=UTF-8',
              Referer: 'https://labs.google/',
              ...browserHeaders,
            },
            body: JSON.stringify(body),
          });
          const text = await res.text();
          let data;
          try {
            data = JSON.parse(text);
          } catch {
            data = text;
          }
          return { status: res.status, ok: res.ok, data };
        }
        """,
        {
            "url": url,
            "token": access_token,
            "body": body,
            "browserHeaders": browser_headers,
        },
    )


async def _ensure_recaptcha_loaded(page: Page) -> None:
    """在项目页上确保 enterprise.js 可用。"""
    ready = await page.evaluate(
        "() => !!(window.grecaptcha?.enterprise?.execute)"
    )
    if ready:
        return

    site_key = settings.recaptcha_site_key
    await page.evaluate(
        """
        (siteKey) => {
          if (document.querySelector('script[data-flow-proxy-recaptcha]')) return;
          const s = document.createElement('script');
          s.src = `https://www.google.com/recaptcha/enterprise.js?render=${siteKey}`;
          s.async = true;
          s.dataset.flowProxyRecaptcha = '1';
          document.head.appendChild(s);
        }
        """,
        site_key,
    )
    await page.wait_for_function(
        "() => typeof grecaptcha !== 'undefined' && "
        "typeof grecaptcha.enterprise !== 'undefined' && "
        "typeof grecaptcha.enterprise.execute === 'function'",
        timeout=settings.captcha_timeout_ms,
    )


class FlowBrowserClient:
    """常驻浏览器 + 预热标签页；每次请求在新标签页执行并关闭。"""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._warmup_page: Page | None = None
        self._start_lock = asyncio.Lock()
        self._session_cookie_lock = asyncio.Lock()
        self._header_store = BrowserHeaderStore()

    async def start(self) -> None:
        async with self._start_lock:
            if self._context is not None:
                return

            self._playwright = await async_playwright().start()
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                *chromium_speed_args(),
            ]

            launch_kwargs: dict[str, Any] = {
                "headless": settings.browser_headless,
                "args": launch_args,
                "channel": BROWSER_CHANNEL,
            }

            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )

            await attach_resource_blocker(self._context)
            attach_header_capture(self._context, self._header_store)

            await self._open_warmup_page()

    async def _open_warmup_page(self) -> None:
        if self._warmup_page and not self._warmup_page.is_closed():
            return

        assert self._context is not None
        url = settings.browser_warmup_url
        logger.info("Opening warmup tab (kept open): %s", url)

        page = await self._context.new_page()
        await page.add_init_script(WEBDRIVER_HIDE_SCRIPT)
        await page.goto(
            url,
            wait_until=GOTO_WAIT_UNTIL,
            timeout=settings.page_timeout_ms,
        )
        self._warmup_page = page
        logger.info("Warmup tab ready")

    async def stop(self) -> None:
        async with self._start_lock:
            if self._warmup_page and not self._warmup_page.is_closed():
                try:
                    await self._warmup_page.close()
                except Exception:
                    pass
            self._warmup_page = None

            if self._context:
                await self._context.close()
            self._context = None

            if self._browser:
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            logger.info("Browser stopped")

    async def _ensure_started(self) -> None:
        if self._context is None:
            await self.start()

    async def _new_work_tab(self) -> Page:
        await self._ensure_started()
        assert self._context is not None
        page = await self._context.new_page()
        await page.add_init_script(WEBDRIVER_HIDE_SCRIPT)
        return page

    @asynccontextmanager
    async def _flow_project_session(
        self,
        project_id: str,
        cookie_value: str,
        *,
        log_label: str,
    ) -> AsyncIterator[tuple[Page, str, dict[str, str]]]:
        await self._ensure_started()
        page = await self._new_work_tab()
        logger.info(
            "New work tab for %s project_id=%s (warmup tab stays open)",
            log_label,
            project_id,
        )
        try:
            assert self._context is not None
            project_url = _project_url(project_id)

            async with self._session_cookie_lock:
                await inject_session_cookie(self._context, cookie_value)
                await page.goto(
                    project_url,
                    wait_until=PROJECT_GOTO_WAIT_UNTIL,
                    timeout=settings.page_timeout_ms,
                )

            access_token = await read_access_token_from_page(page)
            logger.info("access_token: %s", format_token_for_log(access_token))

            browser_headers = await resolve_flow_api_headers(page, self._header_store)
            yield page, access_token, browser_headers
        finally:
            assert self._context is not None
            try:
                await clear_labs_google_session(self._context, page)
            except Exception as exc:
                logger.warning("Failed to clear labs session after request: %s", exc)
            if not page.is_closed():
                await page.close()
            logger.info("Work tab closed for %s project_id=%s", log_label, project_id)

    async def generate_image(self, req: ImageGenerateRequest) -> dict[str, Any]:
        cookie_value = req.next_auth_session_token or req.session_token
        async with self._flow_project_session(
            req.project_id, cookie_value, log_label="image"
        ) as (page, access_token, browser_headers):
            await page.add_script_tag(content=INJECT_RECAPTCHA_SCRIPT)
            await _ensure_recaptcha_loaded(page)

            recaptcha_token = await solve_recaptcha_on_page(
                page,
                action=req.captcha_action,
            )

            body = _build_request_body(req, recaptcha_token)
            api_url = (
                f"{settings.flow_api_base}"
                f"{settings.flow_image_api_path_template.format(project_id=req.project_id)}"
            )

            return await _post_flow_api_in_page(
                page,
                url=api_url,
                access_token=access_token,
                body=body,
                browser_headers=browser_headers,
            )

    async def generate_video(self, req: VideoGenerateRequest) -> dict[str, Any]:
        cookie_value = req.next_auth_session_token or req.session_token
        async with self._flow_project_session(
            req.project_id, cookie_value, log_label="video"
        ) as (page, access_token, browser_headers):
            await page.add_script_tag(content=INJECT_RECAPTCHA_SCRIPT)
            await _ensure_recaptcha_loaded(page)

            captcha_action = req.captcha_action or settings.recaptcha_action_video
            recaptcha_token = await solve_recaptcha_on_page(
                page,
                action=captcha_action,
            )

            body = _build_video_request_body(req, recaptcha_token)
            api_url = f"{settings.flow_api_base}{settings.flow_video_api_path}"

            return await _post_flow_api_in_page(
                page,
                url=api_url,
                access_token=access_token,
                body=body,
                browser_headers=browser_headers,
            )

    async def check_video_status(self, req: VideoStatusCheckRequest) -> dict[str, Any]:
        cookie_value = req.next_auth_session_token or req.session_token
        async with self._flow_project_session(
            req.project_id, cookie_value, log_label="video status"
        ) as (page, access_token, browser_headers):
            body = _build_video_status_request_body(req)
            api_url = f"{settings.flow_api_base}{settings.flow_video_status_api_path}"
            return await _post_flow_api_in_page(
                page,
                url=api_url,
                access_token=access_token,
                body=body,
                browser_headers=browser_headers,
            )

    async def get_media_url(self, req: MediaUrlRequest) -> dict[str, Any]:
        cookie_value = req.next_auth_session_token or req.session_token
        async with self._flow_project_session(
            req.project_id, cookie_value, log_label="media url"
        ) as (page, _access_token, _browser_headers):
            api_url = _media_url_redirect_url(req.name)
            logger.info("Fetching media URL redirect for name=%s", req.name)
            return await _get_media_url_redirect_in_page(
                page,
                url=api_url,
                follow_redirect=req.follow_redirect,
            )


flow_browser = FlowBrowserClient()
