"""浏览器行为常量（不可通过 .env 配置）。"""

BROWSER_CHANNEL = "chromium"
GOTO_WAIT_UNTIL = "domcontentloaded"

SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
SESSION_COOKIE_URL = "https://labs.google"
SESSION_COOKIE_SAME_SITE = "Lax"

NEXT_DATA_TIMEOUT_MS = 30_000
HEADER_CAPTURE_TIMEOUT = 8.0
