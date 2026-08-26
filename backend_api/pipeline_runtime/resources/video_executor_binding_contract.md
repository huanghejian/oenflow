# Video Executor 逻辑资产绑定契约

## V7.3 派生普通图片参考

每个不可拆分原子镜头额外包含两个 `derived_shot_reference`：

```text
shotref::<shot_id>::entry
shotref::<shot_id>::exit
```

它们不是用户注册资产，也不是视频首尾帧参数。Executor 必须先根据 `reference_image_plan` 调用统一图片模型：先生成 entry 状态普通参考图，再以图片编辑方式生成 exit 状态普通参考图；生成文件绑定到上述派生 ID 后，才提交视频模型。派生图片尚未完成时返回 `reference_image_generation_pending`，不得要求用户补 registered_assets。

## 输入

V7 Final Video JSON 中每个 shot 已经包含：

- `model`
- `model_params`
- `duration`
- `prompt_zh`
- `references[]`（逻辑资产）

例如：

```json
{
  "asset_id": "叶澜·基础状态",
  "media_type": "image",
  "purpose": "character_reference",
  "required": true,
  "binding_status": "logical_only"
}
```

## Executor 职责

Executor 根据平台自己的资产库查询：

```text
asset_id
→ 实际 file_id / URL / provider asset handle
```

然后转换成当前视频模型 API 的真实请求字段。

## 缺失真实文件

若某个 required 逻辑资产没有真实文件：

- 该 shot 暂停提交视频 API；
- 返回 `asset_binding_missing`；
- 不重新调用导演 LLM；
- 不重新编译 prompt_zh；
- 不把 prompt_zh 判定为无效。

## optional 真实文件缺失

可直接跳过。

## 建议业务资产表

```json
{
  "叶澜·基础状态": {
    "image": {
      "default": "provider_file_xxx"
    }
  }
}
```

如果业务层拥有正面/侧面/全身等多张文件，可以在 Executor 根据当前 shot 的景别、机位和 purpose 二次选择真实文件；这不影响 V7 路由层的逻辑素材计数。
