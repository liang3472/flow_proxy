from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765

    browser_headless: bool = False
    browser_recaptcha_settle_seconds: float = 2.0
    browser_page_timeout: int = 60
    browser_captcha_timeout: int = 30
    browser_warmup_url: str = "https://labs.google/"

    flow_project_url_template: str = (
        "https://labs.google/fx/tools/flow/project/{project_id}"
    )
    recaptcha_site_key: str = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
    recaptcha_action_image: str = "IMAGE_GENERATION"
    flow_api_base: str = "https://aisandbox-pa.googleapis.com"

    @property
    def page_timeout_ms(self) -> int:
        return self.browser_page_timeout * 1000

    @property
    def captcha_timeout_ms(self) -> int:
        return self.browser_captcha_timeout * 1000


settings = Settings()
