import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.browser.flow_client import flow_browser
from src.config import settings
from src.models import (
    ImageGenerateRequest,
    ImageGenerateResponse,
    MediaUrlRequest,
    MediaUrlResponse,
    VideoGenerateRequest,
    VideoGenerateResponse,
    VideoStatusCheckRequest,
    VideoStatusCheckResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("flow_proxy")


def _flow_api_response(result: dict, response_cls: type):
    status = int(result.get("status", 500))
    ok = bool(result.get("ok"))
    data = result.get("data")

    if not ok:
        err_msg = data
        if isinstance(data, dict):
            err_msg = data.get("error", {}).get("message") or str(data)
        return response_cls(
            ok=False,
            status=status,
            data=data,
            error=str(err_msg) if err_msg else f"HTTP {status}",
        )

    return response_cls(ok=True, status=status, data=data)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting Playwright browser...")
    await flow_browser.start()
    yield
    logger.info("Stopping Playwright browser...")
    await flow_browser.stop()


app = FastAPI(
    title="Flow Proxy",
    description="Google Flow 图片/视频生成与媒体 URL 代理：浏览器会话 + 页面内转发 API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/images/generate", response_model=ImageGenerateResponse)
async def generate_image(req: ImageGenerateRequest):
    """
    接收图片生成任务：
    1. 按 project_id 打开 Flow 项目页
    2. 注入脚本并执行 reCAPTCHA（IMAGE_GENERATION）
    3. 在浏览器上下文中调用 batchGenerateImages
    4. 将 Google API 响应原样返回
    """
    try:
        result = await flow_browser.generate_image(req)
    except Exception as exc:
        logger.exception("Image generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _flow_api_response(result, ImageGenerateResponse)


@app.post("/api/v1/videos/generate", response_model=VideoGenerateResponse)
async def generate_video(req: VideoGenerateRequest):
    """
    接收视频生成任务：
    1. 按 project_id 打开 Flow 项目页
    2. 注入脚本并执行 reCAPTCHA（VIDEO_GENERATION）
    3. 在浏览器上下文中调用 batchAsyncGenerateVideoText
    4. 将 Google API 响应原样返回
    """
    try:
        result = await flow_browser.generate_video(req)
    except Exception as exc:
        logger.exception("Video generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _flow_api_response(result, VideoGenerateResponse)


@app.post("/api/v1/videos/status", response_model=VideoStatusCheckResponse)
async def check_video_status(req: VideoStatusCheckRequest):
    """
    查询异步视频生成状态（batchCheckAsyncVideoGenerationStatus）：
    1. 打开项目页获取 access_token 与浏览器头
    2. 无需 reCAPTCHA
    3. 透传 Google API 响应
    """
    try:
        result = await flow_browser.check_video_status(req)
    except Exception as exc:
        logger.exception("Video status check failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _flow_api_response(result, VideoStatusCheckResponse)


@app.post("/api/v1/media/url", response_model=MediaUrlResponse)
async def get_media_url(req: MediaUrlRequest):
    """
    解析 media 下载/播放地址（labs.google media.getMediaUrlRedirect）：
    1. 打开项目页并携带 Cookie
    2. 调用 tRPC 重定向接口
    3. 返回 data.url（可选跟随重定向）
    """
    try:
        result = await flow_browser.get_media_url(req)
    except Exception as exc:
        logger.exception("Media URL resolve failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return _flow_api_response(result, MediaUrlResponse)


def run():
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
