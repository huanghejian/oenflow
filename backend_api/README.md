# 短剧分镜 API + 后端脚本接入方案

## A 阶段导演页面

当前首页已改为 A 阶段导演工作台。页面可以编辑本次调用使用的
`director_prompt`，并输入项目参数、逻辑资产、上一集连续性和整集剧本。
提交后只请求 `POST /v1/director-plan`，展示、复制和下载 A 阶段 JSON；不会
自动运行后续 Router、Prompt Compiler 或视频 API。

默认 Prompt 由 `GET /v1/director-prompt` 读取。页面修改只影响当前请求，
不会覆盖服务端的 `pipeline_runtime/resources/director_prompt.md`。自定义 Prompt
会作为 System Prompt 发送，并在模型的 User JSON 中剥离，避免重复注入。

OpenRouter Key 只放在 `backend_api/.env` 的 `OPENROUTER_API_KEY` 中。不要把 Key
写进前端、请求体或仓库。OpenRouter 导演调用仍为单次整集调用；因此不需要
把 `reasoning_details` 回传到第二轮消息。

## V7.3 剪辑点原子模式

新生产按真实剪辑点拆镜：没有切镜的连续动作整体作为一个 `single_take=true / indivisible=true` 原子镜头；硬切、匹配剪辑、隐藏剪辑或淡入淡出才建立下一原子。Packer 不合并这种镜头，Router 也不能为了成本再次切分。

每个最终镜头同时输出：

- `prompt_zh`：完整视频提示词；
- `reference_image_plan.entry_state_reference_prompt_zh`：动作开始状态普通图片参考提示词；
- `reference_image_plan.exit_state_reference_edit_prompt_zh`：动作结束状态图片编辑提示词；
- 两个 `shotref::*` 派生逻辑图片资产，它们已经计入视频模型图片容量；
- `cut_in / cut_out`：实际剪辑边界。

参考图片由同一个图片模型先生成开始状态，再以编辑方式生成结束状态。它们是普通图片参考，不是视频 API 的首尾帧控制参数。

这套示例把生产链拆成三个清晰职责：

```text
业务输入
  ↓
POST /v1/director-plan
  ↓ OpenAI Responses API，只负责导演 A JSON
POST /v1/compile-video-plan
  ↓ 本地确定性 Python 流水线
Final Video JSON
  ↓
POST /v1/executor/bind
  ↓ 逻辑 asset_id 绑定真实 file_id / URL
各视频供应商 Adapter → H3 / Seedance / Wan API
```

OpenAI Responses API 支持通过 `instructions` 注入导演规则、通过 `input` 传入当前项目数据，并能生成 JSON 输出。当前示例使用 `text.format.type=json_schema`；官方文档建议支持时优先使用 JSON Schema，而不是旧的 JSON mode。代码读取 SDK 的 `response.output_text`，并检查 `status` 与 `incomplete_details`。

官方资料：

- https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- https://developers.openai.com/api/reference/cli/resources/beta/subresources/responses

## 1. 目录

```text
backend_api/
├─ app/
│  ├─ main.py                 # HTTP 接口
│  ├─ director_service.py     # OpenAI 导演调用
│  ├─ pipeline_service.py     # 后端脚本编排
│  └─ executor_binding.py     # 逻辑素材绑定
├─ pipeline_runtime/
│  ├─ resources/
│  │  ├─ director_prompt.md
│  │  └─ model_registry.json
│  └─ scripts/
│     └─ run_pipeline.py 等
├─ tests/smoke_compile.py
├─ requirements.txt
└─ Dockerfile
```

`director_prompt.md` 是唯一发给大模型的导演规则。`model_registry.json` 不发送给大模型，只交给后端 Router。

## 2. 本地启动

PowerShell：

```powershell
cd backend_api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

将 `.env` 中的值配置为实际密钥和模型。不要把 `.env` 提交到 Git。

默认使用 OpenAI Responses API。如需使用 OpenRouter 的 Claude Opus 5：

```dotenv
DIRECTOR_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DIRECTOR_MODEL=anthropic/claude-opus-5
OPENROUTER_MAX_OUTPUT_TOKENS=110000
OPENROUTER_REASONING_EFFORT=medium
```

OpenRouter 使用兼容 OpenAI 的 `POST /chat/completions` 协议，通过
`Authorization: Bearer <key>` 认证。适配器只发送
`director_prompt.md + 当前 A 阶段输入`，并用 JSON Schema 约束模型只输出
紧凑的 `A1c` 内部 JSON。后端会补回资产目录、固定单镜属性、十维完整字段、
`prompt_core`、空间与比例对象，对页面和现有 Python 流水线仍返回标准 V7.3 A JSON。
`reasoning.effort=medium` 对应中档思考强度。当前目录模型 ID 已验证为
`anthropic/claude-opus-5`，当前请求上限设为 110000 tokens，并在额度预检
返回 402 时按可负担上限的 90% 自动降额重试一次。单次导演请求不需要
多轮续接，所以响应中的 `reasoning_details` 不会写回下一次请求。

如需使用自定义 Claude Converse 网关：

```dotenv
DIRECTOR_PROVIDER=claude_converse
CLAUDE_CONVERSE_URL=https://your-gateway.example/v1/claude/converse
CLAUDE_REGION=us-west-2
CLAUDE_CONVERSE_API_KEY=sk-your-key
# 网关有默认模型时可以不填；否则填写网关要求的 modelId
CLAUDE_DIRECTOR_MODEL=global.anthropic.claude-opus-5
CLAUDE_MAX_OUTPUT_TOKENS=128000
CLAUDE_THINKING_EFFORT=medium
```

Claude 网关通过 `Authorization: Bearer <key>` 认证，并使用 Bedrock Converse 风格的 `system / messages / inferenceConfig` 请求结构。适配器把 `region=us-west-2` 与 `model=global.anthropic.claude-opus-5` 统一追加到 endpoint query，不放进请求 JSON。附件 Java 注释中的 `-v1` 形式已被当前网关实测判定为无效；这里使用当前网关和 Bedrock inference profile 均接受的真实 ID。`opus-5` 不发送低温参数，并通过 `additionalModelRequestFields.thinking.type=adaptive` 与 `output_config.effort=medium` 使用中等思考强度；响应解析会跳过 `reasoningContent`，取第一个真正的 `text`。网关返回结果后仍会经过本地导演 JSON 契约与完整流水线验收。

Claude 请求统一经过 Python 版 `LongTimeHttp`：连接超时 60 秒、读取超时 30 分钟、写入超时 100 秒、最大连接数 64、空闲连接保留 16 分钟，并仅对连接失败自动重试。它与 Java `LongTimeHttp` 的关键行为一致；服务器主动返回的 502/503 不会自动重试，以避免重复计费。

```powershell
$env:OPENAI_API_KEY='sk-...'
$env:OPENAI_DIRECTOR_MODEL='你们选定的模型ID'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问 `http://127.0.0.1:8000/docs` 可查看 FastAPI 自动接口文档。

## 3. 推荐调用方式

### 3.1 第一次生成整集

需要同时得到低、中、高三档时，调用（Demo 页面使用此接口）：

```text
POST /v1/episode/generate-all-tiers
```

它只调用一次导演 API 生成 A JSON，然后用同一份 A JSON 并行编译三档，返回 `director_plan` 和 `tiers.low / tiers.medium / tiers.high`。

只需要单档时，调用：

```text
POST /v1/episode/generate-plan
```

请求体就是：

```json
{
  "user_params": {
    "project_type": "短剧",
    "aspect_ratio": "9:16",
    "target_resolution": "720P",
    "routing_tier": "medium",
    "enable_continuity_tracking": true,
    "user_feedback": ""
  },
  "registered_assets": {
    "scenes": [],
    "roles": [],
    "props": []
  },
  "global_visual_lock": "东方玄幻真人短剧",
  "previous_continuity": {},
  "script": {
    "episode_id": "EP001",
    "content": "整集剧本正文"
  },
  "tier": "medium",
  "target_resolution": "720P"
}
```

内部执行一次导演 API，再运行：

```text
spatial_validator.py
→ shot_packer.py
→ video_router.py
→ prompt_compiler.py
→ validate_final.py
```

### 3.2 已有 A JSON 后切换档位

不要再次调用大模型。直接请求：

```text
POST /v1/compile-video-plan
```

```json
{
  "director_plan": {"这里放已保存的A阶段JSON": true},
  "tier": "high",
  "target_resolution": "720P"
}
```

同一份 A JSON 可以分别编译 LOW、MEDIUM、HIGH，这正是本项目三档文件的生成方式。

### 3.3 绑定真实素材

Final JSON 中 references 先保持 `logical_only`。业务资产库维护：

```json
{
  "叶澜·基础状态": {"file_id": "provider_file_001"},
  "叶家主殿外山门区域": {"url": "https://cdn.example.com/scene.jpg"}
}
```

传给：

```text
POST /v1/executor/bind
```

required 素材缺失时，该镜头返回 `asset_binding_missing`；optional 素材缺失时直接跳过。不要因此重新调用导演或重新编译提示词。

`ready_for_provider_adapter` 之后，由开发同事按 `model` 分发给各供应商 Adapter：

```text
higgsfield-h3 → H3Adapter
seedance-2.0 → Seedance20Adapter
seedance-2.5 → Seedance25Adapter
wan-3.0 → Wan30Adapter
```

每个 Adapter 只负责把统一字段转换成供应商请求：

```text
prompt_zh      → provider prompt
duration       → provider duration
model_params   → provider preset/options
references     → provider file_id/url 参数
```

## 4. 离线验证后端脚本

该测试不调用 OpenAI，只验证已有 A JSON 能否通过后端流水线：

```powershell
cd backend_api
$env:PYTHONPATH=(Get-Location).Path
python tests/smoke_compile.py ..\work\EP001\EP001_A导演输出.json --tier low
python tests/smoke_compile.py ..\work\EP001\EP001_A导演输出.json --tier high
python tests/cut_take_contract.py ..\work\EP001\EP001_A导演输出.json
```

## 5. 生产环境必须补的部分

- 把同步接口改成队列任务：HTTP 只创建 job，Worker 执行导演与编译。
- 用数据库保存 `director_plan`、三档 Final JSON、OpenAI `response_id`、脚本版本和 `model_registry` 版本。
- 用对象存储保存大 JSON，不要把 50 万字符结果长期塞在消息队列中。
- 为 `episode_id + script_hash + assets_hash + prompt_version` 建幂等键，防止重复扣费。
- 对 OpenAI 调用做超时、429/5xx 指数退避；不要对 4xx 数据错误盲目重试。
- 检查 `response.status`；若因 `max_output_tokens` 不完整，不得把半截 JSON 送入后端脚本。
- `director_prompt.md`、`model_registry.json` 和后端脚本必须版本化；价格或成功率变化只重跑 Router，不重做导演。
- API Key 只能保存在服务端密钥管理系统，不能下发浏览器或客户端。
- 供应商执行层需要记录每个 shot 的 provider job id、重试次数、输出 URL、积分和失败原因。
