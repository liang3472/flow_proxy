#!/usr/bin/env python3
"""
测试 Flow Proxy 视频生成接口。

用法（先启动服务: python -m src.main）:

  python scripts/test_generate_video.py ^
    --project-id "你的项目UUID" ^
    --session-token "ya29.xxx" ^
    --prompt "cat" ^
    --aspect-ratio VIDEO_ASPECT_RATIO_LANDSCAPE

  python scripts/test_generate_video.py --health-only

  # 查询异步视频状态（media name 来自 generate 响应）
  python scripts/test_generate_video.py --status-only --media-name d6f87f88-ca67-415d-aaa8-a0368a155925

  python scripts/test_generate_video.py --url-only --media-name dff3b58e-8d20-4c75-a82b-f6cdb16116f7
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _base_url() -> str:
    explicit = os.getenv("FLOW_PROXY_URL")
    if explicit:
        return explicit.rstrip("/")
    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", "8765")
    return f"http://{host}:{port}"


def _request(
    method: str,
    url: str,
    *,
    body: dict | None = None,
    timeout: float,
) -> tuple[int, dict | str]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except urllib.error.URLError as exc:
        raise SystemExit(f"请求失败: {exc}") from exc

    try:
        parsed: dict | str = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    _load_dotenv(repo_root / ".env")

    parser = argparse.ArgumentParser(description="测试 /api/v1/videos/generate")
    parser.add_argument(
        "--base-url",
        default=_base_url(),
        help="服务地址，默认读 HOST/PORT 或 FLOW_PROXY_URL",
    )
    parser.add_argument("--health-only", action="store_true", help="只调用 /health")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="调用 POST /api/v1/videos/status（需 --media-name）",
    )
    parser.add_argument(
        "--url-only",
        action="store_true",
        help="调用 POST /api/v1/media/url 解析下载链接（需 --media-name）",
    )
    parser.add_argument(
        "--no-follow-redirect",
        action="store_true",
        help="与 --url-only 合用：不跟随重定向，仅返回 Location",
    )
    parser.add_argument(
        "--media-name",
        action="append",
        default=[],
        metavar="UUID",
        help="异步 media name，可多次指定；或环境变量 FLOW_VIDEO_MEDIA_NAME（逗号分隔）",
    )
    parser.add_argument(
        "--project-id",
        default=os.getenv("FLOW_PROJECT_ID", ""),
        help="Flow 项目 ID（或环境变量 FLOW_PROJECT_ID）",
    )
    parser.add_argument(
        "--session-token",
        default=os.getenv("FLOW_SESSION_TOKEN", ""),
        help="NextAuth Cookie（或 FLOW_SESSION_TOKEN）",
    )
    parser.add_argument(
        "--prompt",
        default=os.getenv("FLOW_PROMPT", "cat"),
        help="提示词（或 FLOW_PROMPT）",
    )
    parser.add_argument(
        "--aspect-ratio",
        default=os.getenv(
            "FLOW_VIDEO_ASPECT_RATIO", "VIDEO_ASPECT_RATIO_LANDSCAPE"
        ),
        help="video_aspect_ratio（或 FLOW_VIDEO_ASPECT_RATIO）",
    )
    parser.add_argument(
        "--model-key",
        default=os.getenv("FLOW_VIDEO_MODEL_KEY", "veo_3_1_t2v_lite"),
        help="video_model_key（或 FLOW_VIDEO_MODEL_KEY）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("FLOW_TEST_TIMEOUT", "300")),
        help="请求超时秒数（打码+提交可能较久，默认 300）",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    media_names = list(args.media_name)
    env_media = os.getenv("FLOW_VIDEO_MEDIA_NAME", "")
    if env_media:
        media_names.extend(n.strip() for n in env_media.split(",") if n.strip())

    print(f"Base URL: {base}\n")

    if args.health_only:
        status, body = _request("GET", f"{base}/health", timeout=10)
        print(f"GET /health -> HTTP {status}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0 if status == 200 else 1

    missing = []
    if not args.project_id:
        missing.append("--project-id / FLOW_PROJECT_ID")
    if not args.session_token:
        missing.append("--session-token / FLOW_SESSION_TOKEN")
    if missing:
        print("缺少必填参数:", ", ".join(missing), file=sys.stderr)
        parser.print_help()
        return 2

    if args.status_only and args.url_only:
        print("--status-only 与 --url-only 不能同时使用", file=sys.stderr)
        return 2

    if args.url_only:
        if not media_names:
            print("缺少 --media-name 或 FLOW_VIDEO_MEDIA_NAME", file=sys.stderr)
            return 2
        if len(media_names) > 1:
            print("--url-only 仅支持单个 --media-name", file=sys.stderr)
            return 2
        payload = {
            "project_id": args.project_id,
            "session_token": args.session_token,
            "name": media_names[0],
            "follow_redirect": not args.no_follow_redirect,
        }
        print("POST /api/v1/media/url")
        print("Request body:")
        safe = {**payload, "session_token": payload["session_token"][:12] + "..."}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        print(f"\n等待响应（timeout={args.timeout}s）...\n")

        status, body = _request(
            "POST",
            f"{base}/api/v1/media/url",
            body=payload,
            timeout=args.timeout,
        )
        print(f"HTTP {status}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        if isinstance(body, dict):
            if body.get("ok"):
                url = (body.get("data") or {}).get("url")
                if url:
                    print(f"\n✓ 媒体 URL: {url}")
                else:
                    print("\n✓ 请求成功（未解析到 url，见 data.raw）")
                return 0
            print("\n✗ 解析失败:", body.get("error") or "unknown", file=sys.stderr)
            return 1
        return 1 if status >= 400 else 0

    if args.status_only:
        if not media_names:
            print("缺少 --media-name 或 FLOW_VIDEO_MEDIA_NAME", file=sys.stderr)
            return 2
        payload = {
            "project_id": args.project_id,
            "session_token": args.session_token,
            "media": [{"name": name} for name in media_names],
        }
        print("POST /api/v1/videos/status")
        print("Request body:")
        safe = {**payload, "session_token": payload["session_token"][:12] + "..."}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
        print(f"\n等待响应（timeout={args.timeout}s）...\n")

        status, body = _request(
            "POST",
            f"{base}/api/v1/videos/status",
            body=payload,
            timeout=args.timeout,
        )
        print(f"HTTP {status}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        if isinstance(body, dict):
            if body.get("ok"):
                print("\n✓ 状态查询成功")
                return 0
            print("\n✗ 查询失败:", body.get("error") or "unknown", file=sys.stderr)
            return 1
        return 1 if status >= 400 else 0

    payload = {
        "project_id": args.project_id,
        "session_token": args.session_token,
        "prompt": args.prompt,
        "video_aspect_ratio": args.aspect_ratio,
        "video_model_key": args.model_key,
    }
    print("POST /api/v1/videos/generate")
    print("Request body:")
    safe = {**payload, "session_token": payload["session_token"][:12] + "..."}
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    print(f"\n等待响应（timeout={args.timeout}s）...\n")

    status, body = _request(
        "POST",
        f"{base}/api/v1/videos/generate",
        body=payload,
        timeout=args.timeout,
    )

    print(f"HTTP {status}")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    if isinstance(body, dict):
        if body.get("ok"):
            print("\n✓ 生成请求成功")
            return 0
        print("\n✗ 生成失败:", body.get("error") or "unknown", file=sys.stderr)
        return 1

    return 1 if status >= 400 else 0


if __name__ == "__main__":
    raise SystemExit(main())
