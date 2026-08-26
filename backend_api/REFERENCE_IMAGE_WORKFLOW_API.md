# 短剧站位图与视频执行工作流 API

版本：`1.0`  
服务地址：`http://127.0.0.1:8000`  
交互式 Swagger：`http://127.0.0.1:8000/docs`

## 1. 工作流概览

```text
获取 Final Video Plan
→ 上传或登记角色、场景、道具图片
→ 选择一个 final shot
→ 生成开始站位图
→ 以开始图为编辑底图生成结束站位图
→ 登记 shotref::<shot_id>::entry / exit
→ 自动绑定视频提示词、原始资产和两张站位图
→ 提交视频生成任务
```

站位图不是从 JSON 中直接读取的图片。JSON 提供生成所需的信息：

- `reference_image_plan.input_asset_ids`：本镜使用的原始图片资产 ID。
- `reference_image_plan.entry_state_reference_prompt_zh`：开始站位图提示词。
- `reference_image_plan.exit_state_reference_edit_prompt_zh`：结束站位图编辑提示词。
- `reference_image_plan.output_asset_ids`：两张派生图片的逻辑资产 ID。

真实模式使用 OpenRouter Images API。开始图请求包含原始资产图片；结束图请求包含刚生成的开始图和原始资产图片。

## 2. 运行模式

| 模式 | `generation_mode` | 行为 | 是否收费 |
| --- | --- | --- | --- |
| Demo | `demo` | 登记本地验收样图或占位图，用于流程调试 | 否 |
| 真实图片模型 | `provider` | 调用 OpenRouter 图片模型依次生成开始图和结束图 | 是 |

真实模式需要后端环境变量：

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_IMAGE_MODEL=openai/gpt-image-2
OPENROUTER_IMAGE_RESOLUTION=1K
OPENROUTER_IMAGE_QUALITY=medium
```

API Key 只保存在后端 `.env`，不得放进浏览器请求或业务 JSON。

## 3. 通用约定

### 3.1 JSON 请求

除图片上传接口外，POST 请求使用：

```http
Content-Type: application/json
```

### 3.2 错误响应

业务校验失败通常返回：

```json
{
  "detail": "错误原因"
}
```

常见状态码：

| HTTP | 含义 |
| --- | --- |
| `200` | 请求成功 |
| `404` | Demo 制品或本地资源不存在 |
| `422` | 参数错误、资产缺失、图片格式错误或上游图片模型调用失败 |

如果 OpenRouter 返回 `402`，当前后端会以 `422` 返回，并在 `detail` 中保留上游 `HTTP 402` 和余额错误信息。

## 4. 健康检查

### `GET /health`

检查 Demo、导演模型和站位图图片模型是否可用。

响应示例：

```json
{
  "ok": true,
  "demo_available": true,
  "generation_available": true,
  "reference_image_demo_available": true,
  "reference_image_provider_available": true
}
```

## 5. 获取图片生成配置

### `GET /v1/workflow/image-generation`

获取真实站位图生成器的当前配置。不会返回 API Key。

响应示例：

```json
{
  "provider": "openrouter",
  "configured": true,
  "model": "openai/gpt-image-2",
  "resolution": "1K",
  "quality": "medium",
  "aspect_ratio": "9:16",
  "prompt_source": "final_video_plan.shots[].reference_image_plan"
}
```

## 6. 图片资产登记

### 6.1 查询资产登记表

### `GET /v1/workflow/assets`

响应示例：

```json
{
  "count": 2,
  "assets": {
    "秦放·基础状态": {
      "asset_id": "秦放·基础状态",
      "file_id": "local-upload::2d885a...",
      "url": "/workflow-assets/2d885a.png",
      "media_type": "image",
      "mime_type": "image/png",
      "source": "user_upload",
      "binding_status": "bound"
    }
  }
}
```

### 6.2 上传并绑定图片

### `POST /v1/workflow/assets/upload?asset_id={asset_id}`

该接口接收原始图片二进制，不使用 multipart。

请求头：

```http
Content-Type: image/png
X-Filename: role.png
```

请求体：图片二进制。

限制：

- 支持 PNG、JPEG、WebP。
- 服务端会校验真实文件魔数，不只检查扩展名。
- 单张图片最大 15MB。
- `asset_id` 必须与 Final Plan 中的逻辑资产 ID 完全一致。

cURL 示例：

```bash
curl -X POST \
  "http://127.0.0.1:8000/v1/workflow/assets/upload?asset_id=%E7%A7%A6%E6%94%BE%C2%B7%E5%9F%BA%E7%A1%80%E7%8A%B6%E6%80%81" \
  -H "Content-Type: image/png" \
  -H "X-Filename: role.png" \
  --data-binary "@role.png"
```

TypeScript 示例：

```ts
const response = await fetch(
  `${API_BASE}/v1/workflow/assets/upload?asset_id=${encodeURIComponent(assetId)}`,
  {
    method: "POST",
    headers: {
      "Content-Type": file.type || "application/octet-stream",
      "X-Filename": encodeURIComponent(file.name),
    },
    body: file,
  },
);
```

响应示例：

```json
{
  "asset_id": "秦放·基础状态",
  "file_id": "local-upload::2d885a...",
  "url": "/workflow-assets/2d885a.png",
  "media_type": "image",
  "mime_type": "image/png",
  "size_bytes": 258123,
  "source": "user_upload",
  "binding_status": "bound"
}
```

### 6.3 登记内置 Demo 图片

### `POST /v1/workflow/assets/seed-demo`

用于本地演示。它把 `work/EP001_V73/生成图片/` 中的图片按文件名登记为逻辑资产。

响应示例：

```json
{
  "seeded_count": 9,
  "assets": []
}
```

## 7. 生成单个分镜的开始图和结束图

### `POST /v1/workflow/reference-images/generate-shot`

这是推荐的成对生成接口。服务端保证先完成开始图，再生成结束图。

### 7.1 请求结构

```json
{
  "episode_id": "EP001",
  "generation_mode": "provider",
  "image_model": "openai/gpt-image-2",
  "demo_case": false,
  "shot": {
    "shot_id": "u001",
    "atomic_ids": ["s001"],
    "model": "seedance-2.0",
    "duration": 4,
    "model_params": {
      "resolution_preset": "720p-fast",
      "human_mode": true,
      "output_count": 1
    },
    "prompt_zh": "该分镜完整的视频生成提示词……",
    "references": [
      {
        "asset_id": "秦放·基础状态",
        "media_type": "image",
        "asset_type": "role",
        "purpose": "character_reference",
        "required": true
      },
      {
        "asset_id": "叶家主殿外山门区域",
        "media_type": "image",
        "asset_type": "scene",
        "purpose": "scene_reference",
        "required": true
      },
      {
        "asset_id": "shotref::u001::entry",
        "media_type": "image",
        "asset_type": "derived_shot_reference",
        "derived": true,
        "derived_role": "entry_state_reference",
        "required": true
      },
      {
        "asset_id": "shotref::u001::exit",
        "media_type": "image",
        "asset_type": "derived_shot_reference",
        "derived": true,
        "derived_role": "exit_state_reference",
        "required": true
      }
    ],
    "reference_image_plan": {
      "usage": "ordinary_image_reference",
      "generation_strategy": "same_image_model_generate_then_edit",
      "input_asset_ids": [
        "秦放·基础状态",
        "叶家主殿外山门区域",
        "叶家护山大阵"
      ],
      "output_asset_ids": {
        "entry": "shotref::u001::entry",
        "exit": "shotref::u001::exit"
      },
      "entry_state_reference_prompt_zh": "完整的开始站位图生成提示词……",
      "exit_state_reference_edit_prompt_zh": "完整的结束站位图编辑提示词……"
    },
    "continuity": {
      "entry": "本镜开始状态",
      "exit": "本镜结束状态",
      "los": "人物视线关系"
    }
  }
}
```

### 7.2 必填字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `episode_id` | 是 | 集数 ID |
| `generation_mode` | 否 | `demo` 或 `provider`，默认 `demo` |
| `image_model` | 真实模式建议提供 | OpenRouter 图片模型；缺省时读取后端配置 |
| `demo_case` | 否 | 兼容字段；真实模式设为 `false` |
| `shot.shot_id` | 是 | Final Shot ID |
| `shot.reference_image_plan.input_asset_ids` | 是 | 生成开始图所用的逻辑图片资产 |
| `shot.reference_image_plan.output_asset_ids` | 是 | 开始图和结束图的派生资产 ID |
| `entry_state_reference_prompt_zh` | 是 | 开始站位图提示词 |
| `exit_state_reference_edit_prompt_zh` | 是 | 结束站位图编辑提示词 |

`prompt_zh`、`references`、`model`、`model_params`、`continuity` 等完整 Final Shot 字段会随请求一并传递，但当前图片执行器主要读取 `shot_id` 和 `reference_image_plan`。完整传递便于后续保存分镜快照和审计。

### 7.3 真实模式内部行为

开始图请求：

```text
entry_state_reference_prompt_zh
+ input_asset_ids 对应的角色/场景/道具图片
→ OpenRouter /api/v1/images
```

结束图请求：

```text
exit_state_reference_edit_prompt_zh
+ 刚生成的开始图
+ input_asset_ids 对应的原始图片
→ OpenRouter /api/v1/images
```

### 7.4 成功响应

```json
{
  "job_id": "b8469df...",
  "episode_id": "EP001",
  "shot_id": "u001",
  "status": "completed",
  "generation_strategy": "generate_entry_then_edit_exit",
  "generation_mode": "openrouter_images_api",
  "provider": "openrouter",
  "image_model": "openai/gpt-image-2",
  "aspect_ratio": "9:16",
  "prompt_source": "final_video_plan.shots[u001].reference_image_plan",
  "input_asset_ids": [
    "秦放·基础状态",
    "叶家主殿外山门区域",
    "叶家护山大阵"
  ],
  "entry": {
    "status": "completed",
    "asset_id": "shotref::u001::entry",
    "prompt_zh": "完整开始图提示词……",
    "image_url": "/workflow-generated/b8469df_entry.png",
    "mime_type": "image/png"
  },
  "exit": {
    "status": "completed",
    "asset_id": "shotref::u001::exit",
    "prompt_zh": "完整结束图提示词……",
    "image_url": "/workflow-generated/b8469df_exit.png",
    "source_image_url": "/workflow-generated/b8469df_entry.png",
    "mime_type": "image/png"
  },
  "usage": {
    "entry": {
      "cost": 0.05
    },
    "exit": {
      "cost": 0.05
    }
  },
  "registry": {
    "registered_count": 2,
    "assets": []
  }
}
```

### 7.5 常见错误

缺少原始资产：

```json
{
  "detail": "请先上传或登记该分镜使用的图片资产：秦放·基础状态"
}
```

OpenRouter 余额不足：

```json
{
  "detail": "OpenRouter 图片生成失败（HTTP 402）：This request requires more credits..."
}
```

## 8. 批量登记 Demo 站位图

### `POST /v1/workflow/reference-images/generate-all`

当前批量接口只用于本地 Demo，不会批量调用真实图片模型，避免一次误生成整集的两倍图片数量。

请求：

```json
{
  "episode_id": "EP001",
  "final_video_plan": {
    "shots": []
  }
}
```

响应：

```json
{
  "mode": "local_demo",
  "completed_count": 49,
  "blocked_count": 0,
  "completed": [],
  "blocked": []
}
```

真实模式应逐镜调用 `/v1/workflow/reference-images/generate-shot`，由调用方控制费用、并发、失败重试和人工验收。

## 9. 自动绑定视频执行资产

### `POST /v1/workflow/bind`

检查每个 Final Shot 的原始图片和派生站位图是否齐全，并生成视频提供商适配器 payload。

请求：

```json
{
  "episode_id": "EP001",
  "final_video_plan": {
    "shots": []
  }
}
```

响应示例：

```json
{
  "ready_count": 1,
  "blocked_count": 0,
  "registry_count": 11,
  "binding_mode": "local_demo_registry",
  "ready": [
    {
      "shot_id": "u001",
      "status": "ready_for_provider_adapter",
      "provider_payload": {
        "shot_id": "u001",
        "model": "seedance-2.0",
        "duration": 4,
        "prompt": "完整视频提示词……",
        "references": [
          {
            "asset_id": "秦放·基础状态",
            "url": "/workflow-assets/role.png",
            "binding_status": "bound"
          },
          {
            "asset_id": "shotref::u001::entry",
            "url": "/workflow-generated/job_entry.png",
            "derived": true,
            "binding_status": "bound"
          },
          {
            "asset_id": "shotref::u001::exit",
            "url": "/workflow-generated/job_exit.png",
            "derived": true,
            "binding_status": "bound"
          }
        ]
      }
    }
  ],
  "blocked": []
}
```

阻塞示例：

```json
{
  "shot_id": "u002",
  "status": "reference_image_generation_pending",
  "missing_required_asset_ids": [],
  "missing_derived_reference_ids": [
    "shotref::u002::entry",
    "shotref::u002::exit"
  ]
}
```

## 10. 提交视频生成任务

### `POST /v1/workflow/video/submit`

提交前会重新执行一次自动绑定检查。只有资产完整的分镜才会进入队列。

请求：

```json
{
  "episode_id": "EP001",
  "final_video_plan": {
    "shots": []
  }
}
```

当前实现为本地模拟队列：

```json
{
  "mode": "local_demo",
  "submitted_count": 1,
  "blocked_count": 0,
  "registry_count": 11,
  "jobs": [
    {
      "job_id": "3761a4...",
      "shot_id": "u001",
      "status": "queued_demo",
      "mode": "local_video_provider_simulation",
      "bound_asset_ids": [
        "秦放·基础状态",
        "叶家主殿外山门区域",
        "shotref::u001::entry",
        "shotref::u001::exit"
      ],
      "derived_reference_ids": [
        "shotref::u001::entry",
        "shotref::u001::exit"
      ]
    }
  ],
  "blocked": []
}
```

该接口目前不会调用真实视频模型。正式接入 Seedance、H3 等提供商时，应在 `ready[].provider_payload` 基础上实现对应适配器。

## 11. 本地文件与访问地址

| 内容 | 本地目录 | HTTP 地址 |
| --- | --- | --- |
| 用户上传图片 | `backend_api/var/jobs/demo_workflow/uploads/` | `/workflow-assets/{filename}` |
| 真实生成站位图 | `backend_api/var/jobs/demo_workflow/generated/` | `/workflow-generated/{filename}` |
| Demo 输入资产 | `work/EP001_V73/生成图片/` | `/demo-input-assets/{filename}` |
| Demo 验收站位图 | `work/EP001_V73/分镜参考图/` | `/demo-assets/{filename}` |
| 站位图任务清单 | `backend_api/var/jobs/reference_images/{job_id}/manifest.json` | 不直接暴露目录 |
| 资产登记表 | `backend_api/var/jobs/demo_workflow/asset_registry.json` | 通过 `/v1/workflow/assets` 查询 |
| 视频模拟任务 | `backend_api/var/jobs/demo_workflow/video_jobs/` | 不直接暴露目录 |

## 12. 前端推荐调用顺序

```ts
// 1. 查询图片模型配置
await fetch(`${API_BASE}/v1/workflow/image-generation`);

// 2. 查询并补齐资产
await fetch(`${API_BASE}/v1/workflow/assets`);

// 3. 选择一个 final shot，真实生成开始图和结束图
await fetch(`${API_BASE}/v1/workflow/reference-images/generate-shot`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    episode_id: "EP001",
    generation_mode: "provider",
    image_model: "openai/gpt-image-2",
    demo_case: false,
    shot,
  }),
});

// 4. 检查整集绑定
await fetch(`${API_BASE}/v1/workflow/bind`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ episode_id: "EP001", final_video_plan: finalPlan }),
});

// 5. 提交资产完整的分镜
await fetch(`${API_BASE}/v1/workflow/video/submit`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ episode_id: "EP001", final_video_plan: finalPlan }),
});
```

## 13. 当前限制与后续建议

1. 真实站位图只支持逐镜生成；批量真实生成尚未开放。
2. 开始图和结束图必须使用同一个成对接口，暂不支持单独重试其中一张。
3. 画幅当前固定为 `9:16`；分辨率和质量由后端环境变量控制。
4. 每次任务清单保存提示词、模型、资产 ID、图片地址和 usage；尚未额外保存完整 `source_shot.json` 快照。
5. 视频提交当前是本地模拟队列，尚未调用真实视频提供商。
6. 建议后续增加独立开始图/结束图重试接口、完整请求快照、幂等键、费用上限、队列并发限制和人工验收状态。
