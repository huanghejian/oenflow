# 镜序 · A 阶段导演台

单页输入可编辑的导演 System Prompt、项目参数、逻辑资产 JSON、上一集连续性
和完整剧本，通过一次导演模型调用生成 A 阶段 JSON；用户点击“下一步”后，
再运行当前档位的确定性 Router 和 Prompt Compiler，为每个分镜展示拼接完成的
`prompt_zh` 与模型候选评分表。

## 启动

在项目根目录运行：

```powershell
.\启动Demo.ps1
```

页面地址为 `http://localhost:3000`，后端地址为 `http://127.0.0.1:8000`。

生成前在 `backend_api/.env` 配置 OpenRouter：

```dotenv
DIRECTOR_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-new-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DIRECTOR_MODEL=anthropic/claude-opus-5
OPENROUTER_MAX_OUTPUT_TOKENS=110000
OPENROUTER_REASONING_EFFORT=medium
```

## 使用

1. 修改或保留页面自动加载的导演 Prompt。
2. 填写集数、画幅、分辨率、路由档位、视觉锁与可选反馈。
3. 粘贴 `registered_assets` JSON、可选的 `previous_continuity` 和整集剧本。
4. 点击“生成 A 阶段结果”。A 阶段完成后点击“下一步：查看拼接提示词和评分”。
5. 展开每个分镜，复制完整 `prompt_zh`，并查看最终模型与 preset、选择理由、质量分、可靠性、调用积分、
   预计可用积分、档位分及硬淘汰原因；也可切到 A 阶段 JSON 后复制、下载。

Prompt 的页面修改只影响当前请求，不会覆盖服务端默认文件。API Key 只由本地
后端读取，不会进入浏览器代码、请求体或下载结果。
