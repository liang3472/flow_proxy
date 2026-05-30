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
