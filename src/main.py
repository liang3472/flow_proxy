import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.browser.flow_client import flow_browser
from src.config import settings
from src.models import (
    ImageGenerateRequest,
    ImageGenerateResponse,
    VideoGenerateRequest,
    VideoGenerateResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("flow_proxy")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Starting Playwright browser...")
    await flow_browser.start()
    yield
    logger.info("Stopping Playwright browser...")
    await flow_browser.stop()


app = FastAPI(
    title="Flow Proxy",
    description="Google Flow 图片/视频生成代理：浏览器打码 + 页面内转发 API",
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

    status = int(result.get("status", 500))
    ok = bool(result.get("ok"))
    data = result.get("data")

    if not ok:
        err_msg = data
        if isinstance(data, dict):
            err_msg = data.get("error", {}).get("message") or str(data)
        return ImageGenerateResponse(
            ok=False,
            status=status,
            data=data,
            error=str(err_msg) if err_msg else f"HTTP {status}",
        )

    return ImageGenerateResponse(ok=True, status=status, data=data)


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

    status = int(result.get("status", 500))
    ok = bool(result.get("ok"))
    data = result.get("data")

    if not ok:
        err_msg = data
        if isinstance(data, dict):
            err_msg = data.get("error", {}).get("message") or str(data)
        return VideoGenerateResponse(
            ok=False,
            status=status,
            data=data,
            error=str(err_msg) if err_msg else f"HTTP {status}",
        )

    return VideoGenerateResponse(ok=True, status=status, data=data)


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
