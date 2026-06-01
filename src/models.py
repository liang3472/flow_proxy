from typing import Any

from pydantic import BaseModel, Field


class ImageGenerateRequest(BaseModel):
    project_id: str = Field(..., description="Flow 项目 ID")
    session_token: str = Field(
        ...,
        description="用于注入 Cookie __Secure-next-auth.session-token",
    )
    next_auth_session_token: str | None = Field(
        default=None,
        description="NextAuth Cookie 值；不传则使用 session_token 注入 Cookie",
    )
    prompt: str = Field(..., description="图片生成提示词")
    image_aspect_ratio: str = Field(
        ...,
        description="宽高比枚举，如 IMAGE_ASPECT_RATIO_LANDSCAPE",
        examples=["IMAGE_ASPECT_RATIO_LANDSCAPE"],
    )
    image_model_name: str = Field(
        default="NARWHAL",
        description="图片模型名称",
    )
    batch_id: str | None = Field(
        default=None,
        description="mediaGenerationContext.batchId，不传则自动生成 UUID",
    )
    seed: int | None = Field(
        default=None,
        description="随机种子，不传则服务端随机生成",
    )
    image_inputs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="参考图 imageInputs",
    )
    captcha_action: str = Field(
        default="IMAGE_GENERATION",
        description="reCAPTCHA enterprise action",
    )


class ImageGenerateResponse(BaseModel):
    ok: bool
    status: int
    data: Any | None = None
    error: str | None = None


class VideoGenerateRequest(BaseModel):
    project_id: str = Field(..., description="Flow 项目 ID")
    session_token: str = Field(
        ...,
        description="用于注入 Cookie __Secure-next-auth.session-token",
    )
    next_auth_session_token: str | None = Field(
        default=None,
        description="NextAuth Cookie 值；不传则使用 session_token 注入 Cookie",
    )
    prompt: str = Field(..., description="视频生成提示词")
    video_aspect_ratio: str = Field(
        ...,
        description="宽高比枚举，如 VIDEO_ASPECT_RATIO_LANDSCAPE",
        examples=["VIDEO_ASPECT_RATIO_LANDSCAPE"],
    )
    video_model_key: str = Field(
        default="veo_3_1_t2v_lite",
        description="视频模型 key",
    )
    batch_id: str | None = Field(
        default=None,
        description="mediaGenerationContext.batchId，不传则自动生成 UUID",
    )
    seed: int | None = Field(
        default=None,
        description="随机种子，不传则服务端随机生成",
    )
    audio_failure_preference: str = Field(
        default="BLOCK_SILENCED_VIDEOS",
        description="mediaGenerationContext.audioFailurePreference",
    )
    user_paygate_tier: str = Field(
        default="PAYGATE_TIER_ONE",
        description="clientContext.userPaygateTier",
    )
    use_v2_model_config: bool = Field(
        default=True,
        description="是否使用 V2 模型配置",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="requests[].metadata",
    )
    captcha_action: str = Field(
        default="VIDEO_GENERATION",
        description="reCAPTCHA enterprise action",
    )


class VideoGenerateResponse(BaseModel):
    ok: bool
    status: int
    data: Any | None = None
    error: str | None = None


class VideoMediaStatusItem(BaseModel):
    name: str = Field(
        ...,
        description="异步任务 media name，来自 batchAsyncGenerateVideoText 响应",
    )
    project_id: str | None = Field(
        default=None,
        description="项目 ID；不传则使用请求级 project_id",
    )


class VideoStatusCheckRequest(BaseModel):
    project_id: str = Field(..., description="Flow 项目 ID（media 项默认项目）")
    session_token: str = Field(
        ...,
        description="用于注入 Cookie __Secure-next-auth.session-token",
    )
    next_auth_session_token: str | None = Field(
        default=None,
        description="NextAuth Cookie 值；不传则使用 session_token 注入 Cookie",
    )
    media: list[VideoMediaStatusItem] = Field(
        ...,
        min_length=1,
        description="待查询的 media 列表",
    )


class VideoStatusCheckResponse(BaseModel):
    ok: bool
    status: int
    data: Any | None = None
    error: str | None = None


class MediaUrlRequest(BaseModel):
    project_id: str = Field(..., description="Flow 项目 ID（用于打开项目页建立会话）")
    session_token: str = Field(
        ...,
        description="用于注入 Cookie __Secure-next-auth.session-token",
    )
    next_auth_session_token: str | None = Field(
        default=None,
        description="NextAuth Cookie 值；不传则使用 session_token 注入 Cookie",
    )
    name: str = Field(
        ...,
        description="media UUID，与 videos/status 中的 media.name 相同",
    )
    follow_redirect: bool = Field(
        default=True,
        description="为 true 时跟随重定向并返回最终 URL；为 false 时仅返回 Location",
    )


class MediaUrlResponse(BaseModel):
    ok: bool
    status: int
    data: Any | None = None
    error: str | None = None
