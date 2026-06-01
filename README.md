# Flow Proxy

Google Flow 图片/视频生成请求代理服务。收到 API 请求后，用 Playwright 打开对应项目页、在页面内完成 reCAPTCHA 打码，再在同一浏览器上下文中调用 Google Flow API（图片 `batchGenerateImages`、视频 `batchAsyncGenerateVideoText`），并把返回结果透传给调用方。

## 环境要求

- Python 3.11+
- Chromium（通过 Playwright 安装）

## 安装

```bash
cd flow_proxy
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

## 启动

```bash
python -m src.main
```

默认地址：`http://127.0.0.1:8765`

## API

### `POST /api/v1/images/generate`

**请求体示例：**

```json
{
  "project_id": "your-project-uuid",
  "session_token": "ya29.xxx",
  "prompt": "A cinematic landscape at sunset",
  "image_aspect_ratio": "IMAGE_ASPECT_RATIO_LANDSCAPE",
  "image_model_name": "NARWHAL"
}
```

| 字段 | 说明 |
|------|------|
| `project_id` | Flow 项目 ID |
| `session_token` | NextAuth Cookie 值（注入 `__Secure-next-auth.session-token`） |
| `next_auth_session_token` | 可选，仅 Cookie，覆盖 `session_token` |
| `prompt` | 提示词 |
| `image_aspect_ratio` | 如 `IMAGE_ASPECT_RATIO_PORTRAIT` |
| `image_model_name` | 默认 `NARWHAL` |
| `batch_id` | 可选，不传自动生成 |
| `seed` | 可选，不传随机 |
| `image_inputs` | 可选参考图列表 |

**成功响应：**

```json
{
  "ok": true,
  "status": 200,
  "data": { }
}
```

失败时 `ok` 为 `false`，`error` 为错误说明，`data` 为 Google 原始错误体（若有）。

### `POST /api/v1/videos/generate`

**请求体示例：**

```json
{
  "project_id": "your-project-uuid",
  "session_token": "ya29.xxx",
  "prompt": "cat",
  "video_aspect_ratio": "VIDEO_ASPECT_RATIO_LANDSCAPE",
  "video_model_key": "veo_3_1_t2v_lite"
}
```

| 字段 | 说明 |
|------|------|
| `project_id` | Flow 项目 ID |
| `session_token` | NextAuth Cookie 值 |
| `next_auth_session_token` | 可选，仅 Cookie |
| `prompt` | 提示词 |
| `video_aspect_ratio` | 如 `VIDEO_ASPECT_RATIO_LANDSCAPE` |
| `video_model_key` | 默认 `veo_3_1_t2v_lite` |
| `batch_id` | 可选 |
| `seed` | 可选 |
| `audio_failure_preference` | 默认 `BLOCK_SILENCED_VIDEOS` |
| `user_paygate_tier` | 默认 `PAYGATE_TIER_ONE` |
| `use_v2_model_config` | 默认 `true` |
| `metadata` | 可选，请求项 metadata |

响应格式与图片接口相同。视频为异步任务，成功时 `data` 内通常包含 `media` 的 `name`，用于状态查询。

### `POST /api/v1/videos/status`

轮询异步视频生成进度（对应 `batchCheckAsyncVideoGenerationStatus`），**无需打码**，比生成接口更快。

**请求体示例：**

```json
{
  "project_id": "your-project-uuid",
  "session_token": "ya29.xxx",
  "media": [
    { "name": "d6f87f88-ca67-415d-aaa8-a0368a155925" }
  ]
}
```

| 字段 | 说明 |
|------|------|
| `project_id` | Flow 项目 ID（`media[].project_id` 未传时使用） |
| `session_token` | NextAuth Cookie 值 |
| `media` | 待查列表；每项 `name` 必填，`project_id` 可选 |

可同时查询多个 `media`。响应格式与生成接口相同，根据 `data` 内状态字段判断是否完成。

### `GET /health`

健康检查。

## 流程说明

1. **服务启动时**：打开 `BROWSER_WARMUP_URL`（默认 [https://labs.google/](https://labs.google/)）作为预热标签页，**保持不关闭**
2. **收到生成请求时**：注入 Cookie → 新开标签页打开项目页
3. 从 `__NEXT_DATA__.props.pageProps.session.access_token` 读取 API Bearer
4. 打码后在页面内 `fetch` 对应 API（图片 `batchGenerateImages`，视频 `batchAsyncGenerateVideoText`）；状态查询 `batchCheckAsyncVideoGenerationStatus` 仅需 token，不打码
5. 返回 API 响应后**仅关闭该工作标签页**，预热页与浏览器继续保留

## 配置

见 `.env.example`。常用项：

- `BROWSER_HEADLESS=false`：调试时建议有头模式
- `FLOW_PROJECT_URL_TEMPLATE`：项目页 URL 模板

浏览器行为（资源拦截、Cookie 注入、本机 Chrome、API 头捕获等）已写死在 `src/browser/constants.py`，不可通过 `.env` 配置。

## 调用示例

```bash
curl -X POST http://127.0.0.1:8765/api/v1/images/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"project_id\":\"xxx\",\"session_token\":\"ya29...\",\"prompt\":\"hello\",\"image_aspect_ratio\":\"IMAGE_ASPECT_RATIO_LANDSCAPE\"}"

curl -X POST http://127.0.0.1:8765/api/v1/videos/generate ^
  -H "Content-Type: application/json" ^
  -d "{\"project_id\":\"xxx\",\"session_token\":\"ya29...\",\"prompt\":\"cat\",\"video_aspect_ratio\":\"VIDEO_ASPECT_RATIO_LANDSCAPE\"}"

curl -X POST http://127.0.0.1:8765/api/v1/videos/status ^
  -H "Content-Type: application/json" ^
  -d "{\"project_id\":\"xxx\",\"session_token\":\"ya29...\",\"media\":[{\"name\":\"d6f87f88-ca67-415d-aaa8-a0368a155925\"}]}"
```

测试脚本：`scripts/test_generate_image.py`、`scripts/test_generate_video.py`。

视频脚本三种模式：

- 默认：仅 `POST /api/v1/videos/generate`，成功后会打印建议的状态查询命令
- `--status-only --media-name <uuid>`：单次或配合 `--poll` 轮询 `POST /api/v1/videos/status`
- `--poll`：生成成功后自动提取 `data.media[].name` 并轮询直到完成（可加 `--poll-interval`、`--poll-timeout`）

## 注意

- `session_token` 需有效，通常从已登录 Flow 的浏览器请求头中获取。
- 打码依赖 Google reCAPTCHA Enterprise，网络需能访问 `labs.google` 与 `google.com`。
- 本服务仅用于你自有账号与项目的自动化，请遵守 Google 服务条款。
