"""从 Google Flow media 响应解析状态与下载 URL（对齐 flow2api 逻辑）。"""

from __future__ import annotations

from typing import Any

from src.models import ParsedVideoMedia

_URL_KEYS = ("fifeUrl", "videoUrl", "outputUri", "downloadUri")

_DONE_STATUSES = frozenset(
    {
        "MEDIA_GENERATION_STATUS_SUCCESSFUL",
        "MEDIA_GENERATION_STATUS_COMPLETE",
        "MEDIA_GENERATION_STATUS_COMPLETED",
        "MEDIA_GENERATION_STATUS_SUCCEEDED",
        "MEDIA_GENERATION_STATUS_SUCCESS",
        "MEDIA_GENERATION_STATUS_READY",
    }
)
_FAILED_STATUSES = frozenset(
    {
        "MEDIA_GENERATION_STATUS_FAILED",
        "MEDIA_GENERATION_STATUS_ERROR",
        "MEDIA_GENERATION_STATUS_CANCELLED",
    }
)


def find_nested_string(value: Any, keys: tuple[str, ...]) -> str | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for candidate in value.values():
            found = find_nested_string(candidate, keys)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = find_nested_string(item, keys)
            if found:
                return found
    return None


def extract_media_name(media: Any) -> str | None:
    if isinstance(media, list):
        for item in media:
            name = extract_media_name(item)
            if name:
                return name
        return None
    if isinstance(media, dict):
        name = media.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def extract_video_generation_status(media: dict[str, Any]) -> str | None:
    status_block = (
        media.get("mediaMetadata", {}).get("mediaStatus", {})
        if isinstance(media.get("mediaMetadata"), dict)
        else {}
    ) or media.get("mediaStatus", {}) or {}
    if not isinstance(status_block, dict):
        status_block = {}
    status = (
        status_block.get("mediaGenerationStatus")
        or status_block.get("status")
        or media.get("status")
    )
    return str(status) if status else None


def extract_video_url_from_media(media: dict[str, Any]) -> str | None:
    video = media.get("video") if isinstance(media.get("video"), dict) else {}
    candidates = [
        find_nested_string(video, _URL_KEYS),
        find_nested_string(media, _URL_KEYS),
        find_nested_string(video, ("uri", "url")),
    ]
    for candidate in candidates:
        if candidate and (
            candidate.startswith("http://")
            or candidate.startswith("https://")
            or candidate.startswith("/")
        ):
            return candidate
    return None


def extract_video_aspect_ratio(media: dict[str, Any]) -> str | None:
    video = media.get("video") if isinstance(media.get("video"), dict) else {}
    meta = media.get("mediaMetadata") if isinstance(media.get("mediaMetadata"), dict) else {}
    return (
        find_nested_string(video, ("aspectRatio", "videoAspectRatio"))
        or find_nested_string(meta, ("videoAspectRatio", "aspectRatio"))
    )


def parse_video_media_item(
    media: dict[str, Any],
    *,
    fallback_project_id: str | None = None,
) -> ParsedVideoMedia | None:
    name = extract_media_name(media)
    if not name:
        return None
    return ParsedVideoMedia(
        name=name,
        project_id=str(media.get("projectId") or fallback_project_id or "") or None,
        generation_status=extract_video_generation_status(media),
        video_url=extract_video_url_from_media(media),
        aspect_ratio=extract_video_aspect_ratio(media),
    )


def parse_video_google_response(
    data: Any,
    *,
    fallback_project_id: str | None = None,
) -> list[ParsedVideoMedia]:
    if not isinstance(data, dict):
        return []
    media_items = data.get("media")
    if not isinstance(media_items, list):
        return []
    parsed: list[ParsedVideoMedia] = []
    for item in media_items:
        if isinstance(item, dict):
            row = parse_video_media_item(item, fallback_project_id=fallback_project_id)
            if row:
                parsed.append(row)
    return parsed


def is_video_generation_done(status: str | None) -> bool:
    return bool(status and status in _DONE_STATUSES)


def is_video_generation_failed(status: str | None) -> bool:
    return bool(status and status in _FAILED_STATUSES)


def is_video_generation_terminal(status: str | None) -> bool:
    return is_video_generation_done(status) or is_video_generation_failed(status)


def all_video_media_terminal(parsed: list[ParsedVideoMedia]) -> bool:
    if not parsed:
        return False
    return all(is_video_generation_terminal(item.generation_status) for item in parsed)


def any_video_media_failed(parsed: list[ParsedVideoMedia]) -> bool:
    return any(is_video_generation_failed(item.generation_status) for item in parsed)
