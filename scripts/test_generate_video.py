#!/usr/bin/env python3
"""
测试 Flow Proxy 视频生成与状态查询。

用法（先启动服务: python -m src.main）:

  # 仅提交生成
  python scripts/test_generate_video.py ^
    --project-id "你的项目UUID" ^
    --session-token "..." ^
    --prompt "cat"

  # 仅查状态（media name 来自上次 generate 响应）
  python scripts/test_generate_video.py --status-only --media-name d6f87f88-...

  # 生成后自动轮询直到完成（推荐）
  python scripts/test_generate_video.py ^
    --project-id "..." --session-token "..." --prompt "cat" --poll

  python scripts/test_generate_video.py --health-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.media_parse import (  # noqa: E402
    all_video_media_terminal,
    any_video_media_failed,
    parse_video_google_response,
)


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


def _safe_payload(payload: dict) -> dict:
    safe = dict(payload)
    if "session_token" in safe:
        safe["session_token"] = safe["session_token"][:12] + "..."
    return safe


def _extract_media_names(data: Any) -> list[str]:
    return [item.name for item in parse_video_google_response(data)]


def _parsed_from_proxy_body(body: dict, *, project_id: str) -> list:
    parsed = body.get("parsed")
    if isinstance(parsed, list) and parsed:
        return parsed
    return parse_video_google_response(body.get("data"), fallback_project_id=project_id)


def _print_parsed_media(parsed: list) -> None:
    for item in parsed:
        name = item.name if hasattr(item, "name") else item.get("name")
        status = (
            item.generation_status
            if hasattr(item, "generation_status")
            else item.get("generation_status")
        )
        url = item.video_url if hasattr(item, "video_url") else item.get("video_url")
        line = f"  {name}: {status or '(无状态)'}"
        if url:
            line += f"\n    video_url: {url}"
        print(line)


def _call_status(
    base: str,
    *,
    project_id: str,
    session_token: str,
    media_names: list[str],
    timeout: float,
) -> tuple[int, dict | str]:
    payload = {
        "project_id": project_id,
        "session_token": session_token,
        "media": [{"name": name} for name in media_names],
    }
    return _request(
        "POST",
        f"{base}/api/v1/videos/status",
        body=payload,
        timeout=timeout,
    )


def _poll_until_done(
    base: str,
    *,
    project_id: str,
    session_token: str,
    media_names: list[str],
    request_timeout: float,
    poll_interval: float,
    poll_timeout: float,
) -> int:
    deadline = time.monotonic() + poll_timeout
    attempt = 0

    print(f"\n开始轮询状态（间隔 {poll_interval}s，最长 {poll_timeout}s）")
    print(f"media: {', '.join(media_names)}\n")

    while time.monotonic() < deadline:
        attempt += 1
        print(f"--- 第 {attempt} 次查询 ---")
        status, body = _call_status(
            base,
            project_id=project_id,
            session_token=session_token,
            media_names=media_names,
            timeout=request_timeout,
        )
        print(f"HTTP {status}")
        print(json.dumps(body, ensure_ascii=False, indent=2))

        if not isinstance(body, dict) or not body.get("ok"):
            print("\n✗ 状态查询失败", file=sys.stderr)
            return 1

        parsed = _parsed_from_proxy_body(body, project_id=project_id)
        _print_parsed_media(parsed)

        if all_video_media_terminal(parsed):
            if any_video_media_failed(parsed):
                print("\n✗ 视频生成失败", file=sys.stderr)
                return 1
            urls = [
                (p.video_url if hasattr(p, "video_url") else p.get("video_url"))
                for p in parsed
            ]
            urls = [u for u in urls if u]
            print("\n✓ 视频生成完成")
            if urls:
                print("下载地址（fifeUrl，与 flow2api 相同来源）:")
                for url in urls:
                    print(f"  {url}")
            else:
                print("（未解析到 video_url，请检查 data.media）", file=sys.stderr)
            return 0 if urls else 1

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep_s = min(poll_interval, remaining)
        print(f"\n未完成，{sleep_s:.0f}s 后重试...\n")
        time.sleep(sleep_s)

    print("\n✗ 轮询超时", file=sys.stderr)
    return 1


def main() -> int:
    _load_dotenv(_REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(
        description="测试 /api/v1/videos/generate 与 /api/v1/videos/status",
    )
    parser.add_argument(
        "--base-url",
        default=_base_url(),
        help="服务地址，默认读 HOST/PORT 或 FLOW_PROXY_URL",
    )
    parser.add_argument("--health-only", action="store_true", help="只调用 /health")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="只调用 POST /api/v1/videos/status（需 --media-name）",
    )
    parser.add_argument(
        "--poll",
        action="store_true",
        help="generate 成功后自动轮询 /api/v1/videos/status 直到完成",
    )
    parser.add_argument(
        "--media-name",
        action="append",
        default=[],
        metavar="UUID",
        help="media name；status-only 必填；与 --poll 联用时覆盖自动提取",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("FLOW_VIDEO_POLL_INTERVAL", "5")),
        help="轮询间隔秒数（默认 5）",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=float(os.getenv("FLOW_VIDEO_POLL_TIMEOUT", "600")),
        help="轮询总超时秒数（默认 600）",
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
        help="单次 HTTP 请求超时秒数（默认 300）",
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

    if args.status_only:
        if not media_names:
            print("缺少 --media-name 或 FLOW_VIDEO_MEDIA_NAME", file=sys.stderr)
            return 2
        print("POST /api/v1/videos/status")
        print("Request body:")
        payload = {
            "project_id": args.project_id,
            "session_token": args.session_token,
            "media": [{"name": name} for name in media_names],
        }
        print(json.dumps(_safe_payload(payload), ensure_ascii=False, indent=2))
        print(f"\n等待响应（timeout={args.timeout}s）...\n")

        if args.poll:
            return _poll_until_done(
                base,
                project_id=args.project_id,
                session_token=args.session_token,
                media_names=media_names,
                request_timeout=args.timeout,
                poll_interval=args.poll_interval,
                poll_timeout=args.poll_timeout,
            )

        status, body = _call_status(
            base,
            project_id=args.project_id,
            session_token=args.session_token,
            media_names=media_names,
            timeout=args.timeout,
        )
        print(f"HTTP {status}")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        if isinstance(body, dict) and body.get("ok"):
            parsed = _parsed_from_proxy_body(body, project_id=args.project_id)
            if parsed:
                print("\n解析结果:")
                _print_parsed_media(parsed)
            print("\n✓ 状态查询成功")
            return 0
        print("\n✗ 查询失败:", (body or {}).get("error") if isinstance(body, dict) else body, file=sys.stderr)
        return 1

    payload = {
        "project_id": args.project_id,
        "session_token": args.session_token,
        "prompt": args.prompt,
        "video_aspect_ratio": args.aspect_ratio,
        "video_model_key": args.model_key,
    }
    print("POST /api/v1/videos/generate")
    print("Request body:")
    print(json.dumps(_safe_payload(payload), ensure_ascii=False, indent=2))
    print(f"\n等待响应（timeout={args.timeout}s）...\n")

    status, body = _request(
        "POST",
        f"{base}/api/v1/videos/generate",
        body=payload,
        timeout=args.timeout,
    )

    print(f"HTTP {status}")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    if not isinstance(body, dict) or not body.get("ok"):
        print("\n✗ 生成失败:", body.get("error") if isinstance(body, dict) else "unknown", file=sys.stderr)
        return 1

    print("\n✓ 生成请求成功")

    if not args.poll:
        names = _extract_media_names(body.get("data"))
        if names:
            print("\n提示: 可用以下命令查询状态:")
            print(
                f"  python scripts/test_generate_video.py --status-only "
                f"--media-name {' --media-name '.join(names)}"
            )
            print("  或生成时加 --poll 自动轮询直到完成")
        return 0

    names = media_names or _extract_media_names(body.get("data"))
    if not names:
        print("\n✗ 无法从 generate 响应解析 media name，请手动 --media-name", file=sys.stderr)
        return 1

    return _poll_until_done(
        base,
        project_id=args.project_id,
        session_token=args.session_token,
        media_names=names,
        request_timeout=args.timeout,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
