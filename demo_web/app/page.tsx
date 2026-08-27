"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import RoutingResultPanel from "./components/RoutingResultPanel";
import ReferenceFrameSlots from "./components/ReferenceFrameSlots";
import ShotGroupAnalysisPanel from "./components/ShotGroupAnalysisPanel";
import StepTabs from "./components/StepTabs";
import StoryboardAccordion from "./components/StoryboardAccordion";
import type {
  AnalysisResponse,
  AssetItem,
  AssetPromptResponse,
  AssetSplitResponse,
  AssetRecord,
  AssetUploadToken,
  AutoFlowAssets,
  ComposeResponse,
  FinalShot,
  FlowStep,
  GenerationMode,
  ProjectParams,
  ReferenceManifest,
  RouteResponse,
  RoutingTier,
  Segment,
  SplitResponse,
  SubmitResponse,
} from "./components/autoflowTypes";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const VIDEO_POLL_MS = 10_000;
const ACTIVE_VIDEO_STATUSES = new Set(["queued", "submitting", "running"]);
type PromptTemplateName = "asset-split" | "asset-prompts" | "storyboard-split" | "shot-group-analysis" | "routing-analysis";
type AssetPromptFilter = "all" | "characters" | "scenes" | "items";
type NetworkMode = "direct" | "proxy";
type ReferenceFrameRole = "entry" | "exit";
type PromptVersion = {
  version: string;
  created_at?: string;
  size_bytes?: number;
};
const PROMPT_TEMPLATE_NAMES: PromptTemplateName[] = ["asset-split", "asset-prompts", "storyboard-split", "shot-group-analysis", "routing-analysis"];
const EMPTY_PROMPT_VERSIONS: Record<PromptTemplateName, PromptVersion[]> = {
  "asset-split": [],
  "asset-prompts": [],
  "storyboard-split": [],
  "shot-group-analysis": [],
  "routing-analysis": [],
};
const EMPTY_SELECTED_PROMPT_VERSIONS: Record<PromptTemplateName, string> = {
  "asset-split": "",
  "asset-prompts": "",
  "storyboard-split": "",
  "shot-group-analysis": "",
  "routing-analysis": "",
};

const FLOW_STEPS: Array<{ id: FlowStep; index: string; title: string; caption: string }> = [
  { id: "split", index: "01", title: "识别资产", caption: "剧本 / 资产清单" },
  { id: "assetPrompts", index: "02", title: "资产提示词", caption: "生资产提示词" },
  { id: "assets", index: "03", title: "拆分镜", caption: "资产 / 分镜提示词" },
  { id: "analysis", index: "04", title: "镜头组分析", caption: "连续镜头与切镜边界" },
  { id: "routing", index: "05", title: "路由与首尾帧", caption: "模型评分并行生图" },
  { id: "submit", index: "06", title: "视频生成", caption: "提交分镜视频任务" },
  { id: "compose", index: "07", title: "视频合成", caption: "ffmpeg 合并分镜视频" },
  { id: "finale", index: "08", title: "终章", caption: "查看完整成片" },
];

const EMPTY_ASSETS: AutoFlowAssets = { characters: [], scenes: [], items: [] };
const DEFAULT_STORYBOARD_PROMPT = `以 Seedance 2.0 分镜导演 Agent 指令系统为基础，只完成分镜结构组织与子镜头规划。
必须基于上一步资产清单引用角色、场景、关键道具，不要新增未识别的核心资产。
按 sbid/segment 组织剧情，每个 segment 必须包含 sub_shots，sub_shots 是后续识别连续拍摄和真实切镜边界的基本单位。
每个子镜头保留 duration、content、scene、characters、items、shot_type、camera_movement、entry_state、performance、exit_state、dialogue、continuity_hint、indivisible。
分镜规划需要遵守：台词不遗漏、角色/道具引用准确、空间状态连续、活态表演、自然语言运镜、光影氛围、景别角度多样性。
最终只返回 ai-video 自动流兼容 JSON，不输出审视过程、检查清单或 markdown。`;
const DEFAULT_ANALYSIS_PROMPT = `读取 ordered_sub_shots 中每个小镜头的完整内容，只做镜头组划分，不要继续拆解小镜头。
核心任务是判断相邻小镜头是否属于同一段连续表演：动作、台词、呼吸、视线、情绪、行为意图和身体状态是否自然延续，演员是否无需停下、复位或重新起拍。
景别或运镜名称发生变化不等于切镜；如果摄影机能够通过连续推拉、摇移、跟拍或变焦完成变化，仍应合并。
同一动作的准备、发生、结果，以及一句台词前后的连续动作反应，应优先组成同一个连续表演镜头组。
单个小镜头 duration 大于或等于 4 秒时，可以独立成为 independent 单镜组。
单个小镜头或镜头组总时长小于 4 秒时禁止独立输出，必须优先与同一段连续表演的前后相邻镜头合并，直到总时长达到或超过 4 秒。
如果动作、机位、视点、时空和主体状态连续且没有真实切镜点，则按顺序合并为 continuous_take。
如果不足 4 秒且前后都存在真实切镜点，仍必须与剧情关系更紧密的相邻镜头打包为 min_duration_pack，并保留组内切镜语义，不能伪装成 continuous_take。
除非整份输入总时长本身不足 4 秒，否则最终不得出现不足 4 秒的镜头组。
保持原顺序完整覆盖全部小镜头，不得遗漏、重复、跨越或改写剧情。`;
const DEFAULT_ROUTING_ANALYSIS_PROMPT = `请对每个镜头组内的每一个小镜头 sub_shot 分别进行视频生成难度打分，评估表演、口型、身份一致性、多角色控制、动作、物理交互、运镜、道具、特效和时序连续性。
每个小镜头都必须输出 0-100 难度总分、十项 0-100 维度分、难度等级、判断原因和关键风险。
同时评估镜头组的 motion、spatial、asset_density、continuity 四项整体复杂度，输出镜头组 0-100 汇总难度分，且不得低于组内最难小镜头。
只根据镜头内容判断，不因项目档位刻意改变难度；禁止选择或推荐具体模型和 preset，模型选择由后续确定性路由器完成。
保持 group_id 和 sub_shot.id 与输入顺序一致，完整覆盖所有小镜头。`;
const DEFAULT_ASSET_PROMPT_GENERATION_PROMPT = `请基于已识别资产，为每个角色、场景和关键道具生成可直接用于生资产图的提示词。
要求保留原 id/gid/name，不新增核心资产；每个资产输出 asset_prompt，并分别生成 gpt_image_2、seedream_4、flux_kontext 三套 image_prompts。`;
const DEMO_SCRIPT = `第1集
1-1日 外 场景：叶家主殿外
人物：秦放 叶澜 叶灵 秦族弟子、叶家弟子若干 叶家长老x2
△秦放立于叶家山门之上，双眼冒冷光，抬手一道金色巨剑穿透云层落下，护山大阵瞬间破碎，叶灵与叶家弟子跪地吐血。
秦放（讥笑）：一群蝼蚁！（狂傲）让叶澜出来受死！【字幕：秦放 秦家神子】
叶灵（气愤）：秦放！你欺人太甚！（插入相关画面）入苍龙秘境时，你偷袭暗算我哥，不仅抽他灵根害他修为尽失，现在还要赶尽杀绝！
秦放（戏弄）：叶澜可是我的好兄弟，不就是用来利用的吗？
叶灵（祭出飞剑）：我们跟你拼了！
△叶家弟子站叶灵后祭出飞剑。
△近景，Q版叶澜躲在远处石柱后探脑袋观战，冒冷汗。【字幕：叶澜】
叶澜：真倒霉！我本科刚毕业的大学生，就因为网吧通宵打个游戏，竟然穿越了！还穿成了个废人！
△叶澜小心翼翼退后。
叶澜OS：还是溜之大吉吧……
△秦放眼神瞬间锁定叶澜。
秦放（冷笑）：想逃？
△秦放拂袖一甩，五道光刃飞去，叶澜惊恐。
叶澜OS：完了！刚穿越就要死了！
△叶灵大惊失色。
叶灵：哥！小心！
△光刃淹没叶澜，升起浓烟。
△叶灵流泪，愤怒大吼冲向秦放。
叶灵：我要为我哥报仇！
△叶灵与叶家弟子冲向秦放，秦放轻蔑一笑。
△近景，叶澜看着面板错愕。
△系统面板升起（面板文字下同）
系统VO：恭喜宿主挨一刀激活并夕夕系统，获得筑基大圆满修为，当前领取进度99.99%，只需让秦放砍一刀，即可到账。
叶澜（眼睛冒光）OS：是统子哥，我有救了！
系统VO：奖励领取时限还剩10秒，超时宿主立即死亡！
（十秒倒计时特效）
△叶澜急忙站起。
叶澜（上前，单手叉腰指着秦放，嚣张表情）：喂，那边的儿砸，有本事来砍你爹啊！
△叶灵和叶家弟子停下，均是回头看叶澜。（头上全是问号）
△秦放惊讶，随即蔑笑。
秦放：一只蝼蚁，还敢挑衅本神子！
△秦放瞥了一眼叶灵等人，戏谑。
秦放：让你亲眼看着他们一个个死去而无能为力，也挺有趣……
△秦放正要转向朝叶家人施决。
系统VO：三…
叶澜（焦急，指着秦放破口大骂）：秦放，你个狗娘养的……（电报声）
△秦放顿时黑脸。
△叶家人呆滞。（头上全是感叹号）
叶澜（参考老太太骂街）：你有种就杀我啊！儿砸，你聋了吗？
△秦放双眼冒着红色杀意。
秦放：本神子要把你大卸八块！
系统vo：二。
△秦放朝着叶澜指，剑呼啸飞去。
系统VO（音与上面同步）：一。
△叶澜中剑阴笑。
叶澜OS：终于上当了！
系统VO：奖励领取成功。
△叶澜气息暴涨，秦放被震退数米。
△秦放满脸不可思议。`;

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new Error(`服务返回了无法解析的内容（HTTP ${response.status}）`);
  }
}

function jobHasVideoSource(job: NonNullable<SubmitResponse["jobs"]>[number]): boolean {
  return Boolean(
    job.output_url
    || job.output_video_url
    || job.video_url
    || job.output_video_path
    || job.output_path
    || job.video_path,
  );
}

function composableVideoCount(result: SubmitResponse | null): number {
  return (result?.jobs || []).filter((job) => job.status === "succeeded" && jobHasVideoSource(job)).length;
}

function canComposeVideos(result: SubmitResponse | null): boolean {
  return composableVideoCount(result) >= 2;
}

function videoSrc(job: NonNullable<SubmitResponse["jobs"]>[number]): string {
  const source = job.output_url || job.output_video_url || job.video_url || "";
  if (!source) return "";
  return source.startsWith("/") ? `${API_BASE}${source}` : source;
}

function composeVideoSrc(result: ComposeResponse | null): string {
  const source = result?.output_url || "";
  if (!source) return "";
  return source.startsWith("/") ? `${API_BASE}${source}` : source;
}

function rawAssetUrl(record?: AssetRecord | AssetItem | NonNullable<FinalShot["references"]>[number]): string {
  return record?.public_url || record?.url || record?.image_url || "";
}

function isHttpUrl(value?: string): boolean {
  return /^https?:\/\//i.test(value || "");
}

function assetRecordUrl(record?: AssetRecord): string {
  const source = rawAssetUrl(record);
  if (!source) return "";
  return isHttpUrl(source) ? source : `${API_BASE}${source}`;
}

function displayImageUrl(imageUrl: string): string {
  return isHttpUrl(imageUrl) ? imageUrl : `${API_BASE}${imageUrl}`;
}

function imageExtension(contentType: string): string {
  if (contentType.includes("jpeg") || contentType.includes("jpg")) return "jpg";
  if (contentType.includes("webp")) return "webp";
  return "png";
}

function assetLookupText(value?: string): string {
  return (value || "")
    .replace(/\.(png|jpe?g|webp|gif)$/i, "")
    .replace(/·基础状态|基础状态/g, "")
    .replace(/[\s·_\-:：/\\（）()]/g, "");
}

function assetLookupTerms(...values: Array<string | undefined>): string[] {
  const terms = new Set<string>();
  for (const value of values) {
    if (!value) continue;
    terms.add(value);
    terms.add(assetLookupText(value));
  }
  return [...terms].filter(Boolean);
}

function allAssetItems(assets: AutoFlowAssets): AssetItem[] {
  return [
    ...(assets.characters || []),
    ...(assets.scenes || []),
    ...(assets.items || []),
  ];
}

function buildAssetUrlLookup(assets: AutoFlowAssets, registry: Record<string, AssetRecord>): Record<string, string> {
  const lookup: Record<string, string> = {};
  const registryRows = Object.entries(registry).map(([key, record]) => {
    const url = rawAssetUrl(record);
    const terms = assetLookupTerms(key, record.asset_id, record.original_filename);
    for (const term of terms) {
      if (url) lookup[term] = url;
    }
    return { key, record, url, terms: terms.map(assetLookupText).filter(Boolean) };
  });
  for (const asset of allAssetItems(assets)) {
    const terms = assetLookupTerms(asset.id, asset.gid, asset.name);
    let url = rawAssetUrl(asset);
    if (!url) {
      const normalized = terms.map(assetLookupText).filter(Boolean);
      const matched = registryRows.find((row) =>
        row.url && row.terms.some((left) => normalized.some((right) => left.includes(right) || right.includes(left))),
      );
      url = matched?.url || "";
    }
    if (url) {
      for (const term of terms) lookup[term] = url;
    }
  }
  return lookup;
}

function referenceRole(ref: NonNullable<FinalShot["references"]>[number]): "entry" | "exit" | "" {
  const text = `${ref.asset_id || ""} ${ref.derived_role || ""} ${ref.generated_role || ""} ${ref.purpose || ""}`.toLowerCase();
  if (text.includes("entry") || text.includes("开始") || text.includes("开场")) return "entry";
  if (text.includes("exit") || text.includes("结束") || text.includes("尾帧")) return "exit";
  return "";
}

function promptUsesAsset(prompt: string | undefined, assetId: string): boolean {
  if (!prompt || !assetId) return false;
  const escaped = assetId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`\\[${escaped}\\]`).test(prompt)
    || new RegExp(`(^|[^A-Za-z0-9_])${escaped}($|[^A-Za-z0-9_])`).test(prompt);
}

function shotKey(shot: FinalShot): string {
  return shot.shot_id || shot.group_id || "shot";
}

function missingShotAssetIds(
  shot: FinalShot,
  manifest: ReferenceManifest | undefined,
  assetUrlLookup: Record<string, string>,
): string[] {
  const missing = new Set<string>();
  for (const ref of shot.references || []) {
    const assetId = ref.asset_id || "";
    if (!assetId || ref.required === false) continue;
    if (!ref.derived && !promptUsesAsset(shot.prompt_zh, assetId)) continue;
    const role = ref.derived ? referenceRole(ref) : "";
    const referenceUrl = role === "entry" ? manifest?.entry?.image_url : role === "exit" ? manifest?.exit?.image_url : "";
    const lookupUrl = assetUrlLookup[assetId] || assetUrlLookup[assetLookupText(assetId)];
    const resolvedUrl = referenceUrl || rawAssetUrl(ref) || lookupUrl;
    if (!resolvedUrl || (ref.derived && !isHttpUrl(resolvedUrl))) {
      missing.add(assetId);
    }
  }
  return [...missing];
}

function normalizeReferenceManifest(manifest: ReferenceManifest, assetUrlLookup: Record<string, string>): ReferenceManifest {
  const patchFrame = (frame: ReferenceManifest["entry"]): ReferenceManifest["entry"] => {
    if (!frame?.asset_id) return frame;
    const s3Url = assetUrlLookup[frame.asset_id] || assetUrlLookup[assetLookupText(frame.asset_id)];
    if (!isHttpUrl(s3Url)) return frame;
    return {
      ...frame,
      image_url: s3Url,
      url: s3Url,
      public_url: s3Url,
      status: "uploaded",
    };
  };
  return {
    ...manifest,
    entry: patchFrame(manifest.entry),
    exit: patchFrame(manifest.exit),
  };
}

function patchReferenceFrameInRouteResult(
  current: RouteResponse | null,
  shot: FinalShot,
  role: ReferenceFrameRole,
  record: AssetRecord,
): RouteResponse | null {
  if (!current) return current;
  const key = shotKey(shot);
  const assetId = record.asset_id || (role === "entry" ? shot.reference_image_plan?.output_asset_ids?.entry : shot.reference_image_plan?.output_asset_ids?.exit) || "";
  const registeredUrl = record.public_url || record.image_url || record.url || "";
  const patchManifest = (manifest: ReferenceManifest): ReferenceManifest => {
    if (manifest.shot_id !== key) return manifest;
    return {
      ...manifest,
      status: "completed",
      [role]: {
        ...(manifest[role] || {}),
        asset_id: assetId || manifest[role]?.asset_id,
        image_url: registeredUrl || manifest[role]?.image_url,
        url: registeredUrl || manifest[role]?.url,
        public_url: registeredUrl || manifest[role]?.public_url,
        s3_key: record.s3_key || manifest[role]?.s3_key,
        status: "uploaded",
      },
    };
  };
  const completed = current.reference_generation?.completed || [];
  const exists = completed.some((manifest) => manifest.shot_id === key);
  const nextCompleted = exists
    ? completed.map(patchManifest)
    : [
      ...completed,
      patchManifest({
        shot_id: key,
        status: "completed",
        [role]: { asset_id: assetId, image_url: registeredUrl, url: registeredUrl, public_url: registeredUrl, s3_key: record.s3_key, status: "uploaded" },
      }),
    ];
  const nextShots = (current.final_video_plan?.shots || []).map((item) => {
    if (shotKey(item) !== key) return item;
    return {
      ...item,
      references: (item.references || []).map((ref) => {
        if (ref.asset_id !== assetId && referenceRole(ref) !== role) return ref;
        return { ...ref, url: registeredUrl, image_url: registeredUrl, public_url: registeredUrl };
      }),
    };
  });
  return {
    ...current,
    final_video_plan: current.final_video_plan ? { ...current.final_video_plan, shots: nextShots } : current.final_video_plan,
    reference_generation: {
      ...current.reference_generation,
      completed: nextCompleted,
      completed_count: nextCompleted.length,
      blocked: (current.reference_generation?.blocked || []).filter((manifest) => manifest.shot_id !== key),
    },
  };
}

function patchAssetsWithRecord(assets: AutoFlowAssets, assetId: string, record: AssetRecord): AutoFlowAssets {
  const patchAsset = (asset: AssetItem): AssetItem => {
    if (asset.id !== assetId && asset.gid !== assetId) return asset;
    return {
      ...asset,
      file_id: record.file_id,
      url: record.url,
      image_url: record.image_url || record.url,
      public_url: record.public_url || record.url,
      s3_key: record.s3_key,
      source: record.source,
      mime_type: record.mime_type,
      size_bytes: record.size_bytes,
    };
  };
  return {
    characters: (assets.characters || []).map(patchAsset),
    scenes: (assets.scenes || []).map(patchAsset),
    items: (assets.items || []).map(patchAsset),
  };
}

function patchAssetResponse<T extends { assets?: AutoFlowAssets }>(
  result: T | null,
  assetId: string,
  record: AssetRecord,
): T | null {
  if (!result?.assets) return result;
  return { ...result, assets: patchAssetsWithRecord(result.assets, assetId, record) };
}

function uploadFileWithProgress(
  uploadUrl: string,
  file: File,
  headers: Record<string, string>,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", uploadUrl);
    for (const [key, value] of Object.entries(headers)) {
      request.setRequestHeader(key, value);
    }
    request.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      onProgress(Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100))));
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) {
        onProgress(100);
        resolve();
        return;
      }
      reject(new Error(`S3 上传失败（HTTP ${request.status}）`));
    };
    request.onerror = () => reject(new Error("S3 上传网络错误"));
    request.onabort = () => reject(new Error("S3 上传已取消"));
    request.send(file);
  });
}

async function loadPromptTemplate(name: PromptTemplateName, fallback: string): Promise<string> {
  try {
    const response = await fetch(`${API_BASE}/v1/autoflow/prompts/${name}`, { cache: "no-store" });
    const data = await readJson<{ content?: string; detail?: string }>(response);
    if (!response.ok || !data.content) throw new Error(data.detail || "后端模板读取失败");
    return data.content.trim();
  } catch {
    try {
      const response = await fetch(`/prompts/${name}.txt`, { cache: "no-store" });
      const text = await response.text();
      if (!response.ok || !text.trim()) throw new Error("前端模板读取失败");
      return text.trim();
    } catch {
      if (fallback.trim()) return fallback.trim();
      throw new Error(`提示词模板读取失败：${name}`);
    }
  }
}

async function savePromptTemplate(name: PromptTemplateName, content: string): Promise<{ version?: string }> {
  const response = await fetch(`${API_BASE}/v1/autoflow/prompts/${name}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  const data = await readJson<{ detail?: string; version?: string }>(response);
  if (!response.ok) throw new Error(data.detail || `提示词模板保存失败：${name}`);
  return data;
}

function projectDefaults(): ProjectParams {
  return {
    episode_id: "EP001",
    project_type: "短剧",
    aspect_ratio: "9:16",
    resolution: "720P",
    routing_tier: "medium",
    global_visual_lock: "东方玄幻真人短剧，冷青灰电影质感",
    feedback: "",
  };
}

function assetsHaveGeneratedPrompts(result: AssetSplitResponse | null): boolean {
  if (!result) return false;
  const allAssets = [
    ...(result.assets.characters || []),
    ...(result.assets.scenes || []),
    ...(result.assets.items || []),
  ];
  return allAssets.length > 0 && allAssets.every((asset) => {
    return Boolean(asset.asset_prompt) && Boolean(asset.image_prompts && Object.keys(asset.image_prompts).length);
  });
}

export default function Home() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [networkProxyAvailable, setNetworkProxyAvailable] = useState(false);
  const [xingtuImageAvailable, setXingtuImageAvailable] = useState(false);
  const [openrouterImageAvailable, setOpenrouterImageAvailable] = useState(false);
  const [networkMode, setNetworkMode] = useState<NetworkMode>("direct");
  const [activeStep, setActiveStep] = useState<FlowStep>("split");
  const [projectParams, setProjectParams] = useState<ProjectParams>(() => projectDefaults());
  const [assetPrompt, setAssetPrompt] = useState("");
  const [assetPromptGenerationPrompt, setAssetPromptGenerationPrompt] = useState(DEFAULT_ASSET_PROMPT_GENERATION_PROMPT);
  const [storyboardPrompt, setStoryboardPrompt] = useState(DEFAULT_STORYBOARD_PROMPT);
  const [analysisPrompt, setAnalysisPrompt] = useState(DEFAULT_ANALYSIS_PROMPT);
  const [routingAnalysisPrompt, setRoutingAnalysisPrompt] = useState(DEFAULT_ROUTING_ANALYSIS_PROMPT);
  const [reanalysisPrompt, setReanalysisPrompt] = useState("");
  const [promptVersions, setPromptVersions] = useState<Record<PromptTemplateName, PromptVersion[]>>(EMPTY_PROMPT_VERSIONS);
  const [selectedPromptVersions, setSelectedPromptVersions] = useState<Record<PromptTemplateName, string>>(EMPTY_SELECTED_PROMPT_VERSIONS);
  const [script, setScript] = useState(DEMO_SCRIPT);
  const [assetResult, setAssetResult] = useState<AssetSplitResponse | null>(null);
  const [assetPromptResult, setAssetPromptResult] = useState<AssetPromptResponse | null>(null);
  const [splitResult, setSplitResult] = useState<SplitResponse | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResponse | null>(null);
  const [routeResult, setRouteResult] = useState<RouteResponse | null>(null);
  const [submitResult, setSubmitResult] = useState<SubmitResponse | null>(null);
  const [composeResult, setComposeResult] = useState<ComposeResponse | null>(null);
  const [assetRegistry, setAssetRegistry] = useState<Record<string, AssetRecord>>({});
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});
  const [assetPromptFilter, setAssetPromptFilter] = useState<AssetPromptFilter>("all");
  const [assetPromptPreviewAsset, setAssetPromptPreviewAsset] = useState<AssetItem | null>(null);
  const [assetPromptPreviewVariant, setAssetPromptPreviewVariant] = useState("");
  const [routingDetailShotId, setRoutingDetailShotId] = useState<string | null>(null);
  const [generationMode, setGenerationMode] = useState<GenerationMode>("xingtu");
  const [imageModel, setImageModel] = useState("doubao-seedream-5-0-pro-260628");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const assets = splitResult?.assets || assetPromptResult?.assets || assetResult?.assets || EMPTY_ASSETS;
  const storyContext = splitResult?.story_context || assetPromptResult?.story_context || assetResult?.story_context || {};
  const segments = splitResult?.segments || [];
  const shotGroups = analysisResult?.shot_groups || [];
  const routingShots = useMemo(() => routeResult?.routing_analysis?.shots || [], [routeResult]);
  const finalShots = useMemo(() => routeResult?.final_video_plan?.shots || [], [routeResult]);
  const assetPromptAssets = assetPromptResult?.assets || assetResult?.assets || EMPTY_ASSETS;
  const assetPromptCards = useMemo(() => {
    const groups: Array<{ key: Exclude<AssetPromptFilter, "all">; label: string; glyph: string; items: AssetItem[] }> = [
      { key: "characters", label: "角色", glyph: "角", items: assetPromptAssets.characters || [] },
      { key: "scenes", label: "场景", glyph: "场", items: assetPromptAssets.scenes || [] },
      { key: "items", label: "道具", glyph: "道", items: assetPromptAssets.items || [] },
    ];
    return groups.flatMap((group) => group.items.map((asset) => ({ ...group, asset })));
  }, [assetPromptAssets]);
  const filteredAssetPromptCards = assetPromptFilter === "all" ? assetPromptCards : assetPromptCards.filter((item) => item.key === assetPromptFilter);
  const assetUrlLookup = useMemo(() => buildAssetUrlLookup(assetPromptAssets, assetRegistry), [assetPromptAssets, assetRegistry]);
  const readyAssetCount = assetPromptCards.filter((item) => assetUrlLookup[item.asset.id] || assetUrlLookup[assetLookupText(item.asset.id)]).length;
  const referenceMap = useMemo(() => {
    const map: Record<string, ReferenceManifest> = {};
    for (const manifest of routeResult?.reference_generation?.completed || []) {
      if (manifest.shot_id) map[manifest.shot_id] = normalizeReferenceManifest(manifest, assetUrlLookup);
    }
    for (const manifest of routeResult?.reference_generation?.blocked || []) {
      if (manifest.shot_id && !map[manifest.shot_id]) map[manifest.shot_id] = normalizeReferenceManifest(manifest, assetUrlLookup);
    }
    return map;
  }, [assetUrlLookup, routeResult]);
  const generatedReferenceImageCount = useMemo(
    () => Object.values(referenceMap).reduce(
      (total, manifest) => total + Number(Boolean(manifest.entry?.image_url)) + Number(Boolean(manifest.exit?.image_url)),
      0,
    ),
    [referenceMap],
  );
  const submitMissingAssetsByShot = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const shot of finalShots) {
      const key = shotKey(shot);
      map[key] = missingShotAssetIds(shot, referenceMap[key], assetUrlLookup);
    }
    return map;
  }, [assetUrlLookup, finalShots, referenceMap]);
  const hasSubmitMissingAssets = Object.values(submitMissingAssetsByShot).some((items) => items.length > 0);
  const routingDetailRoute = useMemo(() => {
    if (!routingDetailShotId) return undefined;
    return routingShots.find((route) => route.shot_id === routingDetailShotId || route.source_group === routingDetailShotId);
  }, [routingDetailShotId, routingShots]);
  const routingDetailFinalShot = useMemo(() => {
    if (!routingDetailShotId) return undefined;
    return finalShots.find((shot) => shot.shot_id === routingDetailShotId || shot.group_id === routingDetailShotId);
  }, [finalShots, routingDetailShotId]);
  const completedSteps = useMemo(() => {
    const done = new Set<FlowStep>();
    if (assetResult) done.add("split");
    if (assetPromptResult) done.add("assetPrompts");
    if (splitResult) done.add("assets");
    if (analysisResult) done.add("analysis");
    if (routeResult) done.add("routing");
    if (submitResult) done.add("submit");
    if (composeResult) done.add("compose");
    if (composeResult?.output_url) done.add("finale");
    return done;
  }, [analysisResult, assetPromptResult, assetResult, composeResult, routeResult, splitResult, submitResult]);
  const pollingBatchId = submitResult?.batch_id || "";
  const hasActiveVideoJobs = useMemo(
    () => Boolean(submitResult?.jobs?.some((job) => ACTIVE_VIDEO_STATUSES.has(job.status || ""))),
    [submitResult],
  );
  const activeVideoShotIds = useMemo(() => {
    const shotIds = new Set<string>();
    for (const job of submitResult?.jobs || []) {
      if (job.shot_id && ACTIVE_VIDEO_STATUSES.has(job.status || "")) {
        shotIds.add(job.shot_id);
      }
    }
    return shotIds;
  }, [submitResult]);
  useEffect(() => {
    if (!pollingBatchId || !hasActiveVideoJobs) return;

    let cancelled = false;
    async function refreshBatch() {
      try {
        const response = await fetch(
          `${API_BASE}/v1/autoflow/video/batches/${pollingBatchId}`,
          { cache: "no-store" },
        );
        const data = await readJson<SubmitResponse>(response);
        if (cancelled || !response.ok) return;
        setSubmitResult(data);
        const readyCount = composableVideoCount(data);
        if (readyCount >= 2) {
          setNotice(`已有 ${readyCount} 个分镜视频，可以开始合成。`);
        }
      } catch {
        // 单次轮询失败不清空任务，下一轮继续查询。
      }
    }

    void refreshBatch();
    const timer = window.setInterval(() => void refreshBatch(), VIDEO_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [hasActiveVideoJobs, pollingBatchId]);
  const currentStepIndex = Math.max(0, FLOW_STEPS.findIndex((step) => step.id === activeStep));
  const currentStep = FLOW_STEPS[currentStepIndex] || FLOW_STEPS[0];
  const progressPercent = ((currentStepIndex + 1) / FLOW_STEPS.length) * 100;

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const response = await fetch(`${API_BASE}/health`, { cache: "no-store" });
        const data = await readJson<{
          ok?: boolean;
          network_proxy_available?: boolean;
          openrouter_image_provider_available?: boolean;
          xingtu_image_provider_available?: boolean;
        }>(response);
        if (cancelled) return;
        setBackendOnline(Boolean(response.ok && data.ok));
        setNetworkProxyAvailable(Boolean(data.network_proxy_available));
        setXingtuImageAvailable(Boolean(data.xingtu_image_provider_available));
        setOpenrouterImageAvailable(Boolean(data.openrouter_image_provider_available));
      } catch {
        if (!cancelled) setBackendOnline(false);
      }
    }
    async function loadPromptTemplates() {
      try {
        const [assetSplit, assetPrompts, storyboardSplit, shotGroupAnalysis, routingAnalysis] = await Promise.all([
          loadPromptTemplate("asset-split", ""),
          loadPromptTemplate("asset-prompts", DEFAULT_ASSET_PROMPT_GENERATION_PROMPT),
          loadPromptTemplate("storyboard-split", DEFAULT_STORYBOARD_PROMPT),
          loadPromptTemplate("shot-group-analysis", DEFAULT_ANALYSIS_PROMPT),
          loadPromptTemplate("routing-analysis", DEFAULT_ROUTING_ANALYSIS_PROMPT),
        ]);
        if (cancelled) return;
        setAssetPrompt(assetSplit);
        setAssetPromptGenerationPrompt(assetPrompts);
        setStoryboardPrompt(storyboardSplit);
        setAnalysisPrompt(shotGroupAnalysis);
        setRoutingAnalysisPrompt(routingAnalysis);
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : "提示词模板读取失败");
      }
    }
    void bootstrap();
    void loadPromptTemplates();
    void refreshAllPromptVersions();
    void refreshAssetRegistry();
    return () => {
      cancelled = true;
    };
    // 初始化只需执行一次，版本刷新函数内部只使用稳定的 setState。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectNetworkMode(mode: NetworkMode) {
    resetMessages();
    if (mode === "proxy" && !networkProxyAvailable) {
      setError("网络代理尚未配置：请在后端 .env 设置 CLAUDE_HTTP_PROXY_URL 后重启服务。");
      return;
    }
    setNetworkMode(mode);
    setNotice(mode === "proxy" ? "Claude 请求将通过网络代理发送。" : "Claude 请求将强制直连，不读取系统代理。");
  }

  function selectImageGenerationMode(mode: GenerationMode) {
    setGenerationMode(mode);
    if (mode === "xingtu") setImageModel("doubao-seedream-5-0-pro-260628");
    if (mode === "openrouter") setImageModel("openai/gpt-image-2");
  }

  async function refreshAssetRegistry() {
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/assets`, { cache: "no-store" });
      const data = await readJson<{ assets?: Record<string, AssetRecord>; detail?: string }>(response);
      if (!response.ok) throw new Error(data.detail || "资产登记表读取失败");
      setAssetRegistry(data.assets || {});
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "资产登记表读取失败");
    }
  }

  function updateParam<K extends keyof ProjectParams>(key: K, value: ProjectParams[K]) {
    setProjectParams((current) => ({ ...current, [key]: value }));
    if (key === "routing_tier" || key === "resolution") {
      setRouteResult(null);
      setSubmitResult(null);
      setComposeResult(null);
    }
  }

  function resetMessages() {
    setNotice("");
    setError("");
  }

  function setPromptTemplateContent(name: PromptTemplateName, content: string, selectedVersion = "") {
    if (name === "asset-split") setAssetPrompt(content);
    if (name === "asset-prompts") setAssetPromptGenerationPrompt(content);
    if (name === "storyboard-split") setStoryboardPrompt(content);
    if (name === "shot-group-analysis") setAnalysisPrompt(content);
    if (name === "routing-analysis") setRoutingAnalysisPrompt(content);
    setSelectedPromptVersions((current) => ({ ...current, [name]: selectedVersion }));
  }

  async function refreshPromptVersions(name: PromptTemplateName) {
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/prompts/${name}/versions`, { cache: "no-store" });
      const data = await readJson<{ versions?: PromptVersion[]; detail?: string }>(response);
      if (!response.ok) throw new Error(data.detail || "提示词版本列表读取失败");
      setPromptVersions((current) => ({ ...current, [name]: data.versions || [] }));
    } catch {
      setPromptVersions((current) => ({ ...current, [name]: [] }));
    }
  }

  async function refreshAllPromptVersions() {
    await Promise.all(PROMPT_TEMPLATE_NAMES.map((name) => refreshPromptVersions(name)));
  }

  async function saveCurrentPromptTemplate(name: PromptTemplateName, content: string) {
    const data = await savePromptTemplate(name, content);
    await refreshPromptVersions(name);
    if (data.version) {
      setSelectedPromptVersions((current) => ({ ...current, [name]: data.version || "" }));
    }
    return data;
  }

  async function selectPromptVersion(name: PromptTemplateName, version: string) {
    if (!version) {
      setSelectedPromptVersions((current) => ({ ...current, [name]: "" }));
      return;
    }
    resetMessages();
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/prompts/${name}/versions/${version}`, { cache: "no-store" });
      const data = await readJson<{ content?: string; detail?: string }>(response);
      if (!response.ok || !data.content) throw new Error(data.detail || "提示词版本读取失败");
      setPromptTemplateContent(name, data.content.trim(), version);
      setNotice(`已切换到提示词版本 ${version}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "提示词版本读取失败");
    }
  }

  function canOpenStep(step: FlowStep): boolean {
    if (step === "split") return true;
    if (step === "assetPrompts") return Boolean(assetResult || assetPromptResult);
    if (step === "assets") return Boolean(assetPromptResult || splitResult);
    if (step === "analysis") return Boolean(splitResult);
    if (step === "routing") return Boolean(analysisResult);
    if (step === "submit") return Boolean(routeResult);
    if (step === "compose") return Boolean(submitResult);
    if (step === "finale") return Boolean(composeResult?.output_url);
    return true;
  }

  function renderPromptLabel(name: PromptTemplateName, text: string) {
    const versions = promptVersions[name] || [];
    return (
      <span className="promptLabelRow">
        <span>{text}</span>
        <select
          className="promptVersionSelect"
          value={selectedPromptVersions[name] || ""}
          onChange={(event) => void selectPromptVersion(name, event.target.value)}
          disabled={versions.length === 0 || backendOnline !== true}
          title="选择历史提示词版本"
        >
          <option value="">历史版本</option>
          {versions.map((item) => (
            <option key={item.version} value={item.version}>{item.version}</option>
          ))}
        </select>
      </span>
    );
  }

  function assetPromptPreview(asset: AssetItem) {
    return asset.asset_prompt || asset.localized_prompt || asset.prompt || asset.description || "等待生成生资产提示词";
  }

  function assetHasModelPrompts(asset: AssetItem) {
    return Boolean(asset.image_prompts && Object.keys(asset.image_prompts).length > 0);
  }

  function openAssetPromptPreview(asset: AssetItem) {
    const firstVariant = Object.keys(asset.image_prompts || {})[0] || "";
    setAssetPromptPreviewAsset(asset);
    setAssetPromptPreviewVariant(firstVariant);
  }

  async function runAssetSplit(event?: FormEvent) {
    event?.preventDefault();
    resetMessages();
    setBusy("assets-split");
    setAssetResult(null);
    setAssetPromptResult(null);
    setSplitResult(null);
    setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      await saveCurrentPromptTemplate("asset-split", assetPrompt);
      const response = await fetch(`${API_BASE}/v1/autoflow/assets/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          script,
          asset_prompt: assetPrompt,
          image_models: ["gpt_image_2", "seedream_4", "flux_kontext"],
          use_ai: true,
          use_network_proxy: networkMode === "proxy",
        }),
      });
      const data = await readJson<AssetSplitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "识别资产失败");
      setAssetResult(data);
      setActiveStep("assetPrompts");
      const llm = data.llm as { provider?: string; model?: string } | undefined;
      const modelLabel = llm?.provider ? `已调用 ${llm.provider}${llm.model ? ` / ${llm.model}` : ""}。` : "";
      setNotice(`${modelLabel}资产识别完成：${data.assets.characters.length} 个角色、${data.assets.scenes.length} 个场景、${data.assets.items.length} 个物品。请继续生成生资产提示词。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "识别资产失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLatestAssetSplit() {
    resetMessages();
    setBusy("assets-load");
    setAssetPromptResult(null);
    setSplitResult(null);
    setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/assets/latest`, { cache: "no-store" });
      const data = await readJson<AssetSplitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "加载最近资产识别结果失败");
      setAssetResult(data);
      if (assetsHaveGeneratedPrompts(data)) {
        setAssetPromptResult(data);
        setActiveStep("assets");
        setNotice(`已加载最近资产提示词结果：${data.assets.characters.length} 个角色、${data.assets.scenes.length} 个场景、${data.assets.items.length} 个物品。`);
      } else {
        setAssetPromptResult(null);
        setActiveStep("assetPrompts");
        setNotice(`已加载最近资产识别结果：${data.assets.characters.length} 个角色、${data.assets.scenes.length} 个场景、${data.assets.items.length} 个物品，请继续生成生资产提示词。`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最近资产识别结果失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLatestAssetPrompts() {
    resetMessages();
    setBusy("asset-prompts-load");
    setSplitResult(null);
    setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/assets/prompts/latest`, { cache: "no-store" });
      const data = await readJson<AssetPromptResponse>(response);
      if (!response.ok) throw new Error(data.detail || "加载最近资产提示词结果失败");
      setAssetResult(data);
      setAssetPromptResult(data);
      setActiveStep("assets");
      setNotice(`已加载最近资产提示词结果：${data.assets.characters.length} 个角色、${data.assets.scenes.length} 个场景、${data.assets.items.length} 个物品，可继续拆分镜。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最近资产提示词结果失败");
    } finally {
      setBusy("");
    }
  }

  async function runAssetPrompts() {
    if (!assetResult) {
      setError("请先完成资产识别，再生成生资产提示词。");
      return;
    }
    resetMessages();
    setBusy("asset-prompts");
    setAssetPromptResult(null);
    setSplitResult(null);
    setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      await saveCurrentPromptTemplate("asset-prompts", assetPromptGenerationPrompt);
      const response = await fetch(`${API_BASE}/v1/autoflow/assets/prompts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          script,
          assets: assetResult.assets,
          asset_ledger: assetResult.asset_ledger || null,
          story_context: assetResult.story_context,
          prompt_instruction: assetPromptGenerationPrompt,
          image_models: ["gpt_image_2", "seedream_4", "flux_kontext"],
          use_ai: true,
          use_network_proxy: networkMode === "proxy",
        }),
      });
      const data = await readJson<AssetPromptResponse>(response);
      if (!response.ok) throw new Error(data.detail || "生资产提示词生成失败");
      setAssetPromptResult(data);
      setActiveStep("assets");
      const llm = data.llm as { provider?: string; model?: string } | undefined;
      const modelLabel = llm?.provider ? `已调用 ${llm.provider}${llm.model ? ` / ${llm.model}` : ""}。` : "";
      setNotice(`${modelLabel}生资产提示词完成：${data.assets.characters.length} 个角色、${data.assets.scenes.length} 个场景、${data.assets.items.length} 个物品。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生资产提示词生成失败");
    } finally {
      setBusy("");
    }
  }

  async function runStoryboardSplit() {
    if (!assetPromptResult) {
      setError("请先生成生资产提示词，再拆分镜。");
      return;
    }
    resetMessages();
    setBusy("storyboard-split");
    setSplitResult(null);
    setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      await saveCurrentPromptTemplate("storyboard-split", storyboardPrompt);
      const response = await fetch(`${API_BASE}/v1/autoflow/storyboard/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          script,
          assets: assetPromptResult.assets,
          story_context: assetPromptResult.story_context,
          storyboard_prompt: storyboardPrompt,
          use_ai: true,
          use_network_proxy: networkMode === "proxy",
        }),
      });
      const data = await readJson<SplitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "拆镜失败");
      setSplitResult(data);
      await refreshAssetRegistry();
      setActiveStep("analysis");
      const llm = data.llm as { provider?: string; model?: string } | undefined;
      const modelLabel = llm?.provider ? `已调用 ${llm.provider}${llm.model ? ` / ${llm.model}` : ""}。` : "";
      setNotice(`${modelLabel}拆分镜完成：${data.segments.length} 个分镜，可进入镜头组分析。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "拆镜失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLatestStoryboard() {
    resetMessages();
    setBusy("storyboard-load");
    setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/storyboard/latest`, { cache: "no-store" });
      const data = await readJson<SplitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "加载最近拆分镜结果失败");
      setAssetResult({ assets: data.assets, story_context: data.story_context, llm: data.llm });
      setAssetPromptResult({ assets: data.assets, story_context: data.story_context, llm: data.llm });
      setSplitResult(data);
      await refreshAssetRegistry();
      setActiveStep("analysis");
      setNotice(`已加载最近拆分镜结果：${data.segments.length} 个分镜，可继续镜头组分析。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最近拆分镜结果失败");
    } finally {
      setBusy("");
    }
  }

  async function uploadImageAssetToS3(assetId: string, file: File, progressKey = assetId): Promise<AssetRecord & { detail?: string }> {
    setUploadProgress((current) => ({ ...current, [progressKey]: 2 }));
    const tokenResponse = await fetch(`${API_BASE}/v1/workflow/assets/upload-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: assetId,
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        size_bytes: file.size,
      }),
    });
    const token = await readJson<AssetUploadToken>(tokenResponse);
    if (!tokenResponse.ok) throw new Error(token.detail || "获取 S3 上传令牌失败");
    setUploadProgress((current) => ({ ...current, [progressKey]: 5 }));
    await uploadFileWithProgress(
      token.upload_url,
      file,
      token.headers || { "Content-Type": token.content_type || file.type || "application/octet-stream" },
      (percent) => setUploadProgress((current) => ({ ...current, [progressKey]: percent })),
    );
    const registerResponse = await fetch(`${API_BASE}/v1/workflow/assets/register-s3`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        asset_id: assetId,
        s3_key: token.s3_key,
        url: token.url || token.public_url,
        content_type: token.content_type || file.type,
        size_bytes: file.size,
        original_filename: file.name,
      }),
    });
    const data = await readJson<AssetRecord & { detail?: string }>(registerResponse);
    if (!registerResponse.ok) throw new Error(data.detail || "登记 S3 图片失败");
    const registeredUrl = data.public_url || data.image_url || data.url || "";
    if (!isHttpUrl(registeredUrl)) {
      throw new Error("S3 登记未返回 HTTP URL，请检查后端是否仍在使用旧上传接口。");
    }
    setAssetRegistry((current) => ({ ...current, [assetId]: data }));
    return data;
  }

  async function uploadAsset(assetId: string, file: File) {
    resetMessages();
    setBusy(`upload:${assetId}`);
    try {
      const data = await uploadImageAssetToS3(assetId, file);
      const registeredUrl = data.public_url || data.image_url || data.url || "";
      setAssetResult((current) => patchAssetResponse(current, assetId, data));
      setAssetPromptResult((current) => patchAssetResponse(current, assetId, data));
      setSplitResult((current) => patchAssetResponse(current, assetId, data));
      await refreshAssetRegistry();
      setNotice(`${assetId} 已上传到 S3 并绑定：${registeredUrl}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传图片失败");
    } finally {
      setUploadProgress((current) => {
        const next = { ...current };
        delete next[assetId];
        return next;
      });
      setBusy("");
    }
  }

  async function uploadReferenceFrame(shot: FinalShot, role: ReferenceFrameRole) {
    const key = shotKey(shot);
    const manifest = referenceMap[key];
    const frame = manifest?.[role];
    const assetId = frame?.asset_id || (role === "entry" ? shot.reference_image_plan?.output_asset_ids?.entry : shot.reference_image_plan?.output_asset_ids?.exit) || "";
    const imageUrl = frame?.image_url || "";
    if (!assetId || !imageUrl) {
      setError(`${key} 缺少${role === "entry" ? "开始" : "结束"}站位图，无法上传。`);
      return;
    }
    if (isHttpUrl(imageUrl)) {
      setNotice(`${assetId} 已经是 S3/HTTP 图片，无需重复上传。`);
      return;
    }
    resetMessages();
    setBusy(`upload-reference:${assetId}`);
    const progressKey = assetId;
    try {
      const imageResponse = await fetch(displayImageUrl(imageUrl), { cache: "no-store" });
      if (!imageResponse.ok) throw new Error(`读取本地站位图失败（HTTP ${imageResponse.status}）`);
      const blob = await imageResponse.blob();
      const contentType = blob.type || imageResponse.headers.get("content-type") || "image/png";
      const file = new File([blob], `${key}_${role}.${imageExtension(contentType)}`, { type: contentType });
      const data = await uploadImageAssetToS3(assetId, file, progressKey);
      const registeredUrl = data.public_url || data.image_url || data.url || "";
      setRouteResult((current) => patchReferenceFrameInRouteResult(current, shot, role, data));
      await refreshAssetRegistry();
      setNotice(`${assetId} 已上传到 S3 并回写：${registeredUrl}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传首尾站位图失败");
    } finally {
      setUploadProgress((current) => {
        const next = { ...current };
        delete next[progressKey];
        return next;
      });
      setBusy("");
    }
  }

  async function runAnalysis(reanalyze = false) {
    if (!splitResult) return;
    if (reanalyze && !analysisResult) {
      setError("请先生成或加载镜头组结果，再进行重新分析。");
      return;
    }
    if (reanalyze && !reanalysisPrompt.trim()) {
      setError("请先填写重新分析要求，可指定 s001 或 g001 等编号。");
      return;
    }
    resetMessages();
    setBusy(reanalyze ? "reanalysis" : "analysis");
    if (!reanalyze) setAnalysisResult(null);
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      await saveCurrentPromptTemplate("shot-group-analysis", analysisPrompt);
      const response = await fetch(`${API_BASE}/v1/autoflow/analyze-shot-groups`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          assets,
          story_context: storyContext,
          segments,
          analysis_prompt: analysisPrompt,
          reanalysis_prompt: reanalyze ? reanalysisPrompt.trim() : undefined,
          previous_analysis: reanalyze ? analysisResult : undefined,
          use_ai: true,
          use_network_proxy: networkMode === "proxy",
        }),
      });
      const data = await readJson<AnalysisResponse>(response);
      if (!response.ok) throw new Error(data.detail || "镜头组分析失败");
      setAnalysisResult(data);
      if (reanalyze) {
        setNotice(`重新分析完成：形成 ${data.shot_groups.length} 个镜头组，请确认结果。`);
      } else {
        setActiveStep("routing");
        setNotice(`分析完成：形成 ${data.shot_groups.length} 个镜头组，已进入第五步查看镜头组与表演单元。`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : reanalyze ? "重新分析镜头组失败" : "镜头组分析失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLatestAnalysis() {
    resetMessages();
    setBusy("analysis-load");
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/analyze-shot-groups/latest`, { cache: "no-store" });
      const data = await readJson<AnalysisResponse>(response);
      if (!response.ok) throw new Error(data.detail || "加载最近镜头组分析结果失败");
      if (data.assets && data.story_context && data.segments) {
        setAssetResult({ assets: data.assets, story_context: data.story_context, llm: data.llm });
        setAssetPromptResult({ assets: data.assets, story_context: data.story_context, llm: data.llm });
        setSplitResult({ assets: data.assets, story_context: data.story_context, segments: data.segments, llm: data.llm });
      }
      setAnalysisResult(data);
      setActiveStep("routing");
      setNotice(`已加载最近镜头组分析结果：${data.shot_groups.length} 个镜头组，已进入第五步。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最近镜头组分析结果失败");
    } finally {
      setBusy("");
    }
  }

  async function runRoutingAndReferences(modeOverride?: GenerationMode) {
    if (!analysisResult) return;
    const selectedGenerationMode = modeOverride || generationMode;
    const selectedImageModel = selectedGenerationMode === "xingtu"
      ? "doubao-seedream-5-0-pro-260628"
      : imageModel;
    resetMessages();
    setBusy("routing");
    setSubmitResult(null);
    setComposeResult(null);
    try {
      await saveCurrentPromptTemplate("routing-analysis", routingAnalysisPrompt);
      const response = await fetch(`${API_BASE}/v1/autoflow/route-and-generate-refs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          assets,
          story_context: storyContext,
          shot_groups: shotGroups,
          generation_mode: selectedGenerationMode,
          image_model: selectedGenerationMode !== "demo" ? selectedImageModel : undefined,
          routing_analysis_prompt: routingAnalysisPrompt,
          use_ai_difficulty: true,
          use_network_proxy: networkMode === "proxy",
        }),
      });
      const data = await readJson<RouteResponse>(response);
      if (!response.ok) throw new Error(data.detail || "路由或首尾帧生成失败");
      setRouteResult(data);
      await refreshAssetRegistry();
      setActiveStep("submit");
      const imageCount = (data.reference_generation?.completed || []).reduce(
        (total, manifest) => total + Number(Boolean(manifest.entry?.image_url)) + Number(Boolean(manifest.exit?.image_url)),
        0,
      );
      setNotice(`路由完成：${data.final_video_plan?.shots?.length || 0} 个视频镜头；首尾线稿完成 ${imageCount} 张，阻塞 ${data.reference_generation?.blocked_count || 0}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "路由或首尾帧生成失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLatestRoutingAndReferences(targetStep: "routing" | "submit" = "routing") {
    resetMessages();
    setBusy("routing-load");
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/route-and-generate-refs/latest`, { cache: "no-store" });
      const data = await readJson<RouteResponse>(response);
      if (!response.ok) throw new Error(data.detail || "加载最近路由与首尾帧结果失败");

      const source = data.source_context;
      if (source?.project_params) setProjectParams(source.project_params);
      if (source?.assets) {
        const restoredStoryContext = source.story_context || {};
        setAssetResult({ assets: source.assets, story_context: restoredStoryContext });
        setAssetPromptResult({ assets: source.assets, story_context: restoredStoryContext });
      }
      if (source?.shot_groups) {
        setAnalysisResult({
          assets: source.assets,
          story_context: source.story_context,
          shot_groups: source.shot_groups,
        });
      }
      const savedMode = data.reference_generation?.generation_mode;
      if (savedMode === "demo" || savedMode === "xingtu") setGenerationMode(savedMode);

      setRouteResult(data);
      await refreshAssetRegistry();
      setActiveStep(targetStep);
      const imageCount = (data.reference_generation?.completed || []).reduce(
        (total, manifest) => total + Number(Boolean(manifest.entry?.image_url)) + Number(Boolean(manifest.exit?.image_url)),
        0,
      );
      setNotice(`已加载最近路由与首尾帧：${data.final_video_plan?.shots?.length || 0} 个视频镜头、${imageCount} 张首尾线稿，阻塞 ${data.reference_generation?.blocked_count || 0}。不会重复调用模型或重新生图。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最近路由与首尾帧结果失败");
    } finally {
      setBusy("");
    }
  }

  async function saveRoutingAnalysisPrompt() {
    resetMessages();
    setBusy("routing-prompt-save");
    try {
      const data = await saveCurrentPromptTemplate("routing-analysis", routingAnalysisPrompt);
      setNotice(`路由难度提示词已保存${data.version ? `为版本 ${data.version}` : ""}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "路由难度提示词保存失败");
    } finally {
      setBusy("");
    }
  }

  async function runSubmit(targetShot?: FinalShot) {
    if (!routeResult?.final_video_plan) return;
    const finalVideoPlan = targetShot
      ? { ...routeResult.final_video_plan, batch_shots: routeResult.final_video_plan.shots || [], shots: [targetShot] }
      : routeResult.final_video_plan;
    const shotLabel = targetShot?.shot_id || targetShot?.group_id || "当前镜头";
    resetMessages();
    const blockedShot = (finalVideoPlan.shots || [])
      .map((shot) => {
        const key = shotKey(shot);
        const missing = missingShotAssetIds(shot, referenceMap[key], assetUrlLookup);
        return { key, missing };
      })
      .find((item) => item.missing.length > 0);
    if (blockedShot) {
      setError(`${blockedShot.key} 缺少必要素材：${blockedShot.missing.join("、")}。请先上传或生成对应图片。`);
      return;
    }
    setBusy(targetShot ? `submit:${shotLabel}` : "submit");
    if (!targetShot) {
      setSubmitResult(null);
      setComposeResult(null);
    }
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/video/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          final_video_plan: finalVideoPlan,
          regenerate_existing: Boolean(targetShot),
        }),
      });
      const data = await readJson<SubmitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "视频任务提交失败");
      if (targetShot) {
        setSubmitResult(data);
        setNotice(`${shotLabel} 视频任务提交完成：入队 ${data.submitted_count || 0}，阻塞 ${data.blocked_count || 0}。`);
      } else {
        setSubmitResult(data);
        setActiveStep("compose");
        setNotice(`视频任务提交完成：入队 ${data.submitted_count || 0}，阻塞 ${data.blocked_count || 0}。`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "视频任务提交失败");
    } finally {
      setBusy("");
    }
  }

  async function loadLatestVideoBatch() {
    resetMessages();
    setBusy("video-batch-load");
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/video/batches/latest`, { cache: "no-store" });
      const data = await readJson<SubmitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "加载最后一次生成视频数据失败");
      setSubmitResult(data);
      setActiveStep("submit");
      setNotice(`已加载最后一次视频生成批次：${data.batch_id || "未知批次"}，入队 ${data.submitted_count || 0}，阻塞 ${data.blocked_count || 0}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最后一次生成视频数据失败");
    } finally {
      setBusy("");
    }
  }

  async function runCompose() {
    if (!submitResult?.jobs?.length) return;
    resetMessages();
    const readyCount = composableVideoCount(submitResult);
    if (readyCount < 2) {
      setError("至少需要 2 个已生成视频才能合成。");
      return;
    }
    setBusy("compose");
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/video/compose`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_params: projectParams, submit_result: submitResult, jobs: submitResult.jobs }),
      });
      const data = await readJson<ComposeResponse>(response);
      if (!response.ok) throw new Error(data.detail || "视频合成失败");
      setComposeResult(data);
      if (data.output_url) {
        setActiveStep("finale");
        setNotice(`视频合成完成：${data.input_count || readyCount} 个分镜已合并。`);
      } else {
        setNotice(data.message || "没有可合成的视频文件。");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "视频合成失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="app-shell auto-flow-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">帧</span>
          <div>
            <strong>镜序</strong>
            <span>AI DIRECTOR</span>
          </div>
        </div>
        <StepTabs
          steps={FLOW_STEPS}
          activeStep={activeStep}
          completedSteps={completedSteps}
          canOpenStep={canOpenStep}
          onChange={setActiveStep}
        />
        <div className="sidebar-foot">
          <div className="engine-status"><span />{backendOnline === null ? "正在连接导演引擎" : backendOnline ? "导演引擎就绪" : "本地后端未连接"}</div>
          <p>资产提示词 · 拆镜 · 首尾帧 · 视频生成 · 合成</p>
          <button type="button">七步自动流 <span>›</span></button>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">AUTOFLOW / {projectParams.episode_id}</span>
            <h1>{projectParams.episode_id} · {currentStep.title}</h1>
          </div>
          <div className="top-actions">
            <div className="network-mode-switch" aria-label="Claude 网络连接方式">
              <span>Claude 网络</span>
              <div>
                <button
                  type="button"
                  className={networkMode === "direct" ? "active" : ""}
                  onClick={() => selectNetworkMode("direct")}
                  disabled={Boolean(busy)}
                >
                  直连
                </button>
                <button
                  type="button"
                  className={networkMode === "proxy" ? "active" : ""}
                  onClick={() => selectNetworkMode("proxy")}
                  disabled={Boolean(busy)}
                  title={networkProxyAvailable ? "通过已配置的网络代理请求 Claude" : "未配置 CLAUDE_HTTP_PROXY_URL"}
                >
                  {networkProxyAvailable ? "走代理" : "代理未配置"}
                </button>
              </div>
            </div>
            <span className={backendOnline ? "save-state online-state" : "save-state offline-state"}><i />{backendOnline === null ? "连接中" : backendOnline ? "后端已就绪" : "后端未连接"}</span>
            <button className="quiet-button" type="button" onClick={() => void refreshAssetRegistry()} disabled={Boolean(busy)}>刷新资产</button>
            <button className="avatar" aria-label="用户菜单" type="button">OF</button>
          </div>
        </header>

        <div className="progress-strip"><span style={{ width: `${progressPercent}%` }} /></div>

        <section className="page-wrap autoFlowContent">
          {activeStep !== "assetPrompts" && activeStep !== "assets" && (
            <div className="assetCenterHero autoStepHero">
              <div>
                <span>{currentStep.index} / 07 AUTOFLOW</span>
                <h2>{currentStep.title}</h2>
                <p>{currentStep.caption}</p>
              </div>
              {activeStep === "submit" && (
                <button
                  type="button"
                  className="textButton autoHeroAction"
                  onClick={() => void loadLatestVideoBatch()}
                  disabled={Boolean(busy) || backendOnline !== true}
                >
                  {busy === "video-batch-load" ? "加载中..." : "加载视频列表"}
                </button>
              )}
              <div className="autoHeroStats">
                <span><b>{segments.length}</b> 分镜</span>
                <span><b>{shotGroups.length}</b> 镜头组</span>
                <span><b>{finalShots.length}</b> 视频镜头</span>
              </div>
            </div>
          )}

          {activeStep !== "assetPrompts" && activeStep !== "assets" && (error || notice) && <div className={error ? "message error autoMessage" : "message success autoMessage"}>{error || notice}</div>}

      {activeStep === "split" && (
        <form className="autoStepGrid splitGrid" onSubmit={runAssetSplit}>
          <section className="card">
            <div className="cardHead">
              <div><span>01</span><div><h2>剧本与资产识别提示词</h2><p>第一步只请求大模型识别角色、场景、关键道具，不生成生资产提示词。</p></div></div>
            </div>
            <label className="autoField">
              <span>整集剧本</span>
              <textarea value={script} onChange={(event) => setScript(event.target.value)} required />
            </label>
            <label className="autoField">
              {renderPromptLabel("asset-split", "拆资产提示词")}
              <textarea value={assetPrompt} onChange={(event) => setPromptTemplateContent("asset-split", event.target.value)} required />
            </label>
            <div className="splitActions">
              <button className="generateButton autoPrimaryButton" type="submit" disabled={Boolean(busy) || backendOnline !== true || !assetPrompt.trim()}>
                <span>{busy === "assets-split" ? "正在识别资产..." : "识别资产"}</span><b>→</b>
              </button>
              <button className="textButton" type="button" onClick={() => void loadLatestAssetSplit()} disabled={Boolean(busy) || backendOnline !== true}>
                {busy === "assets-load" ? "正在加载..." : "加载最近识别结果"}
              </button>
            </div>
          </section>

          <section className="card">
            <div className="cardHead">
              <div><span>参数</span><div><h2>项目参数</h2><p>作为自动流全局约束透传给后端。</p></div></div>
            </div>
            <div className="autoParamGrid">
              <label><span>集数 ID</span><input value={projectParams.episode_id} onChange={(e) => updateParam("episode_id", e.target.value)} /></label>
              <label><span>项目类型</span><input value={projectParams.project_type} onChange={(e) => updateParam("project_type", e.target.value)} /></label>
              <label><span>画幅</span><select value={projectParams.aspect_ratio} onChange={(e) => updateParam("aspect_ratio", e.target.value)}><option>9:16</option><option>16:9</option></select></label>
              <label><span>分辨率</span><select value={projectParams.resolution} onChange={(e) => updateParam("resolution", e.target.value)}><option>720P</option><option>1080P</option></select></label>
              <label><span>路由档位</span><select value={projectParams.routing_tier} onChange={(e) => updateParam("routing_tier", e.target.value as RoutingTier)}><option value="low">LOW</option><option value="medium">MEDIUM</option><option value="high">HIGH</option></select></label>
            </div>
            <label className="autoField"><span>全局视觉锁</span><input value={projectParams.global_visual_lock} onChange={(e) => updateParam("global_visual_lock", e.target.value)} /></label>
            <label className="autoField"><span>用户反馈</span><input value={projectParams.feedback} onChange={(e) => updateParam("feedback", e.target.value)} placeholder="可选" /></label>
            {(assetResult || splitResult) && (
              <pre className="autoJsonPreview">
                {JSON.stringify(
                  {
                    assets,
                    story_context: storyContext,
                    segments: splitResult?.segments.slice(0, 2) || [],
                  },
                  null,
                  2,
                )}
              </pre>
            )}
          </section>
        </form>
      )}

      {activeStep === "assetPrompts" && (
        <section className="assetCenterPage">
          <div className="assetCenterHero">
            <div>
              <span>02 / {assetPromptCards.length} ASSETS READY</span>
              <h2>资产中心</h2>
              <p>按图示卡片管理已识别资产，并通过生资产提示词模板补齐多模型提示词。</p>
            </div>
            <div className="autoInlineActions">
              <button type="button" className="textButton" onClick={() => void loadLatestAssetPrompts()} disabled={Boolean(busy) || backendOnline !== true}>
                {busy === "asset-prompts-load" ? "正在加载..." : "加载最近资产提示词"}
              </button>
              <button type="button" className="textButton" onClick={() => void refreshAssetRegistry()} disabled={Boolean(busy)}>刷新资产</button>
              <button type="button" className="textButton" onClick={() => setActiveStep("assets")} disabled={!assetPromptResult}>下一步：拆分镜</button>
            </div>
          </div>

          {(error || notice) && <div className={error ? "message error autoMessage assetCenterMessage" : "message success autoMessage assetCenterMessage"}>{error || notice}</div>}

          <details className="assetTemplateDrawer">
            <summary>生资产提示词模板</summary>
            <label className="autoField">
              {renderPromptLabel("asset-prompts", "模板内容")}
              <textarea value={assetPromptGenerationPrompt} onChange={(event) => setPromptTemplateContent("asset-prompts", event.target.value)} required />
            </label>
          </details>

          <div className="assetCenterToolbar">
            <div className="assetFilterTabs">
              <button type="button" className={assetPromptFilter === "all" ? "active" : ""} onClick={() => setAssetPromptFilter("all")}>全部 {assetPromptCards.length}</button>
              <button type="button" className={assetPromptFilter === "characters" ? "active" : ""} onClick={() => setAssetPromptFilter("characters")}>角色 {assetPromptAssets.characters.length}</button>
              <button type="button" className={assetPromptFilter === "scenes" ? "active" : ""} onClick={() => setAssetPromptFilter("scenes")}>场景 {assetPromptAssets.scenes.length}</button>
              <button type="button" className={assetPromptFilter === "items" ? "active" : ""} onClick={() => setAssetPromptFilter("items")}>道具 {assetPromptAssets.items.length}</button>
            </div>
            <p><i />输出每个资产的生图提示词，供下一步拆分镜和资产生成使用。</p>
          </div>

          <div className="assetCenterGrid">
            {filteredAssetPromptCards.map(({ asset, key, label, glyph }) => {
              const record = assetRegistry[asset.id];
              const imageUrl = assetRecordUrl(record);
              return (
                <article className={record ? "assetCenterCard bound" : "assetCenterCard"} key={`${key}:${asset.id}`}>
                  <div className="assetCenterPreview">
                    <b>{label}</b>
                    {imageUrl ? <div className="assetCenterImage" style={{ backgroundImage: `url(${imageUrl})` }} aria-label={asset.name} /> : <span>{glyph}</span>}
                    <small>{record ? "素材已绑定" : "等待素材"}</small>
                  </div>
                  <div className="assetCenterCopy">
                    <strong>{asset.name}</strong>
                    <em>{asset.id}</em>
                    <p>{assetPromptPreview(asset)}</p>
                  </div>
                </article>
              );
            })}
          </div>

          <div className="assetCenterActionBar">
            <div><strong>{readyAssetCount} 个资产已配置素材</strong><span>生成提示词后可进入第 3 步拆分镜。</span></div>
            <button className="textButton" type="button" onClick={() => void refreshAssetRegistry()} disabled={Boolean(busy)}>检查缺失资产</button>
            <button className="generateButton" type="button" onClick={() => void runAssetPrompts()} disabled={Boolean(busy) || !assetResult || backendOnline !== true || !assetPromptGenerationPrompt.trim()}>
              <span>{busy === "asset-prompts" ? "正在生成生资产提示词..." : "确认资产并生成提示词"}</span><b>→</b>
            </button>
          </div>

          {assetPromptResult && <pre className="autoJsonPreview">{JSON.stringify({ assets: assetPromptResult.assets, story_context: assetPromptResult.story_context }, null, 2)}</pre>}
        </section>
      )}

      {activeStep === "assets" && (
        <section className="assetCenterPage">
          <div className="assetCenterHero">
            <div>
              <span>03 / {assetPromptCards.length} ASSETS PROMPTED</span>
              <h2>资产提示词确认</h2>
              <p>检查每个资产的提示词结果，再基于拆分镜模板生成分镜与子镜头。</p>
            </div>
            <div className="autoInlineActions">
              <button type="button" className="textButton" onClick={() => void loadLatestStoryboard()} disabled={Boolean(busy) || backendOnline !== true}>
                {busy === "storyboard-load" ? "正在加载..." : "加载最近拆分镜"}
              </button>
              <button type="button" className="textButton" onClick={() => void refreshAssetRegistry()} disabled={Boolean(busy)}>刷新资产</button>
              <button type="button" className="textButton" onClick={() => setActiveStep("analysis")} disabled={!splitResult}>下一步：镜头组分析</button>
            </div>
          </div>

          {(error || notice) && <div className={error ? "message error autoMessage assetCenterMessage" : "message success autoMessage assetCenterMessage"}>{error || notice}</div>}

          <details className="assetTemplateDrawer">
            <summary>拆分镜提示词模板</summary>
            <label className="autoField">
              {renderPromptLabel("storyboard-split", "拆分镜提示词")}
              <textarea value={storyboardPrompt} onChange={(event) => setPromptTemplateContent("storyboard-split", event.target.value)} required />
            </label>
          </details>

          <div className="assetCenterToolbar">
            <div className="assetFilterTabs">
              <button type="button" className={assetPromptFilter === "all" ? "active" : ""} onClick={() => setAssetPromptFilter("all")}>全部 {assetPromptCards.length}</button>
              <button type="button" className={assetPromptFilter === "characters" ? "active" : ""} onClick={() => setAssetPromptFilter("characters")}>角色 {assetPromptAssets.characters.length}</button>
              <button type="button" className={assetPromptFilter === "scenes" ? "active" : ""} onClick={() => setAssetPromptFilter("scenes")}>场景 {assetPromptAssets.scenes.length}</button>
              <button type="button" className={assetPromptFilter === "items" ? "active" : ""} onClick={() => setAssetPromptFilter("items")}>道具 {assetPromptAssets.items.length}</button>
            </div>
            <p><i />点击“资产提示词”查看该资产的三套候选，确认后进入拆分镜。</p>
          </div>

          <div className="assetCenterGrid">
            {filteredAssetPromptCards.map(({ asset, key, label, glyph }) => {
              const record = assetRegistry[asset.id];
              const uploading = busy === `upload:${asset.id}`;
              const uploadPercent = uploadProgress[asset.id] || 0;
              const imageUrl = assetRecordUrl(record);
              return (
                <article className={record ? "assetCenterCard bound" : "assetCenterCard"} key={`storyboard:${key}:${asset.id}`}>
                  <div className="assetCenterPreview">
                    <b>{label}</b>
                    {imageUrl ? <div className="assetCenterImage" style={{ backgroundImage: `url(${imageUrl})` }} aria-label={asset.name} /> : <span>{glyph}</span>}
                    <small>{uploading ? `上传 ${uploadPercent}%` : record ? "素材已绑定" : "等待素材"}</small>
                    {uploading ? <div className="assetUploadProgress"><span style={{ width: `${uploadPercent}%` }} /></div> : null}
                  </div>
                  <div className="assetCenterCopy">
                    <strong>{asset.name}</strong>
                    <em>{asset.id}</em>
                    <p>{assetPromptPreview(asset)}</p>
                  </div>
                  <footer>
                    <label>
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp"
                        disabled={Boolean(busy)}
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) uploadAsset(asset.id, file);
                          event.currentTarget.value = "";
                        }}
                      />
                      <span>{uploading ? `上传 ${uploadPercent}%` : record ? "替换图片" : "上传图片"}</span>
                    </label>
                    <button type="button" onClick={() => openAssetPromptPreview(asset)} disabled={!assetHasModelPrompts(asset)}>资产提示词</button>
                  </footer>
                </article>
              );
            })}
          </div>

          <div className="assetCenterActionBar">
            <div><strong>{readyAssetCount} 个资产已配置素材</strong><span>资产提示词确认后，可提交拆分镜大模型分析。</span></div>
            <button className="textButton" type="button" onClick={() => void refreshAssetRegistry()} disabled={Boolean(busy)}>检查缺失资产</button>
            <button className="generateButton" type="button" onClick={() => void runStoryboardSplit()} disabled={Boolean(busy) || !assetPromptResult || backendOnline !== true}>
              <span>{busy === "storyboard-split" ? "正在拆分镜..." : "基于资产拆分镜"}</span><b>→</b>
            </button>
          </div>

          {splitResult && <pre className="autoJsonPreview">{JSON.stringify({ story_context: storyContext, segments: splitResult.segments.slice(0, 2) }, null, 2)}</pre>}
        </section>
      )}

      {(activeStep === "assetPrompts" || activeStep === "assets") && assetPromptPreviewAsset && (
        <div className="assetPromptModalBackdrop">
          <button className="assetPromptModalCloseLayer" type="button" aria-label="关闭资产提示词弹窗" onClick={() => setAssetPromptPreviewAsset(null)} />
          <section className="assetPromptModal" role="dialog" aria-modal="true" aria-label={`${assetPromptPreviewAsset.name} 资产提示词`}>
            <header>
              <div>
                <span>{assetPromptPreviewAsset.id}</span>
                <h3>{assetPromptPreviewAsset.name}</h3>
                <p>{assetPromptPreviewAsset.asset_prompt || "以下为该资产的候选提示词。"}</p>
              </div>
              <button type="button" onClick={() => setAssetPromptPreviewAsset(null)}>关闭</button>
            </header>
            {(() => {
              const promptEntries = Object.entries(assetPromptPreviewAsset.image_prompts || {});
              const activeEntry = promptEntries.find(([variant]) => variant === assetPromptPreviewVariant) || promptEntries[0];
              return (
                <div className="assetPromptTabContent">
                  <div className="assetPromptTabs">
                    {promptEntries.map(([variant]) => (
                      <button
                        key={variant}
                        type="button"
                        className={activeEntry?.[0] === variant ? "active" : ""}
                        onClick={() => setAssetPromptPreviewVariant(variant)}
                      >
                        {variant}
                      </button>
                    ))}
                  </div>
                  {activeEntry ? (
                    <article className="assetPromptPanel">
                      <strong>{activeEntry[0]}</strong>
                      <p>{activeEntry[1]}</p>
                    </article>
                  ) : null}
                </div>
              );
            })()}
          </section>
        </div>
      )}

      {activeStep === "analysis" && (
        <section className="assetCenterPage">
          <section className="analysisWorkspace">
            <div className="analysisTemplateShell">
              <details className="assetTemplateDrawer analysisTemplateDrawer">
                <summary>镜头组分析提示词模板</summary>
                <label className="autoField analysisPrompt">
                  {renderPromptLabel("shot-group-analysis", "分析提示词")}
                  <textarea value={analysisPrompt} onChange={(event) => setPromptTemplateContent("shot-group-analysis", event.target.value)} />
                </label>
              </details>
              <div className="analysisActions">
                <button className="generateButton autoPrimaryButton" type="button" onClick={() => void runAnalysis()} disabled={Boolean(busy) || !splitResult}>
                  <span>{busy === "analysis" ? "正在分析镜头组..." : "分析镜头组"}</span><b>→</b>
                </button>
                <button className="textButton" type="button" onClick={() => void loadLatestAnalysis()} disabled={Boolean(busy) || backendOnline !== true}>
                  {busy === "analysis-load" ? "正在加载..." : "加载最近镜头组分析"}
                </button>
              </div>
            </div>
            <section className="card">
              <div className="cardHead">
                <div><span>03 结果</span><div><h2>分镜与子镜头</h2><p>这里展示第三步拆出的分镜；展开分镜后可继续查看每个子镜头。</p></div></div>
              </div>
              <StoryboardAccordion segments={segments as Segment[]} />
            </section>
          </section>
        </section>
      )}

      {activeStep === "routing" && (
        <section className="assetCenterPage">
          <div className="analysisTemplateShell routingTemplateShell">
            <details className="assetTemplateDrawer analysisTemplateDrawer">
              <summary>逐镜头难度分析提示词</summary>
              <label className="autoField analysisPrompt">
                {renderPromptLabel("routing-analysis", "提示词内容")}
                <textarea
                  value={routingAnalysisPrompt}
                  onChange={(event) => setPromptTemplateContent("routing-analysis", event.target.value)}
                />
              </label>
              <div className="routingTemplateOptions">
                <select value={generationMode} onChange={(event) => selectImageGenerationMode(event.target.value as GenerationMode)}>
                  <option value="demo">Demo 占位图</option>
                  <option value="xingtu">星图 5.0 Pro（真实）</option>
                </select>
                <input value={imageModel} onChange={(event) => setImageModel(event.target.value)} disabled={generationMode === "demo"} />
                <span className={`imageProviderState ${generationMode !== "demo" && ((generationMode === "xingtu" && xingtuImageAvailable) || (generationMode === "openrouter" && openrouterImageAvailable)) ? "ready" : ""}`}>
                  {generationMode === "demo"
                    ? "占位图 · 9:16"
                    : generationMode === "xingtu"
                      ? `${xingtuImageAvailable ? "已配置" : "密钥未配置"} · 同步文生图 · 首尾并行 · 2K · 9:16 · ${shotGroups.length * 2} 张线稿`
                      : `${openrouterImageAvailable ? "已配置" : "密钥未配置"} · 9:16`}
                </span>
                <button
                  type="button"
                  className="textButton"
                  onClick={() => void saveRoutingAnalysisPrompt()}
                  disabled={Boolean(busy) || !routingAnalysisPrompt.trim()}
                >
                  {busy === "routing-prompt-save" ? "保存中..." : "保存难度提示词"}
                </button>
              </div>
            </details>
            <div className="analysisActions">
              <button
                type="button"
                className="generateButton autoPrimaryButton"
                onClick={() => void runRoutingAndReferences()}
                disabled={
                  Boolean(busy)
                  || !analysisResult
                  || !routingAnalysisPrompt.trim()
                  || (generationMode === "xingtu" && !xingtuImageAvailable)
                  || (generationMode === "openrouter" && !openrouterImageAvailable)
                }
              >
                <span>{busy === "routing" ? "路由与生图中..." : generationMode === "demo" ? "执行路由 + 占位图" : `执行路由 + 生成 ${shotGroups.length * 2} 张线稿`}</span><b>→</b>
              </button>
              <button
                type="button"
                className="textButton"
                onClick={() => void loadLatestRoutingAndReferences("submit")}
                disabled={Boolean(busy) || backendOnline !== true}
              >
                {busy === "routing-load" ? "加载中..." : "加载最近路由与首尾帧"}
              </button>
            </div>
          </div>
          {analysisResult && (
            <section className="card">
              <div className="cardHead">
                <div><span>04 结果</span><div><h2>镜头组与表演单元</h2><p>展示第四步分析形成的连续拍摄镜头组、组内子镜头和表演状态。</p></div></div>
              </div>
              <section className="reanalysisBox">
                <div>
                  <strong>重新分析要求</strong>
                  <span>可指定分镜 s001、镜头组 g001，或填写全局重组规则</span>
                </div>
                <textarea
                  value={reanalysisPrompt}
                  onChange={(event) => setReanalysisPrompt(event.target.value)}
                  placeholder="例如：重新检查 g001 内每个相邻边界；存在反打、机位变化或动作已完成时必须切开，只保留真正的一镜到底段落。"
                />
                <button
                  className="reanalysisButton"
                  type="button"
                  onClick={() => void runAnalysis(true)}
                  disabled={Boolean(busy) || !reanalysisPrompt.trim()}
                >
                  {busy === "reanalysis" ? "正在重新分析..." : "按要求重新分析"}<b>↻</b>
                </button>
              </section>
              <ShotGroupAnalysisPanel groups={shotGroups} />
            </section>
          )}
        </section>
      )}

      {activeStep === "submit" && (
        <section className="assetCenterPage">
          <section className="card autoFullCard">
          <div className="cardHead">
            <div><span>06</span><div><h2>视频生成</h2><p>提交镜头组路由方案、首尾帧图片、资产图片和分镜提示词，等待每个分镜视频输出。</p></div></div>
            <div className="autoInlineActions submitRouteActions">
              <button
                type="button"
                className="textButton"
                onClick={() => void runSubmit()}
                disabled={Boolean(busy) || hasActiveVideoJobs || !routeResult?.final_video_plan || generatedReferenceImageCount < finalShots.length * 2 || hasSubmitMissingAssets}
                title={hasActiveVideoJobs ? "已有视频任务生成中，请等待完成后再批量生成" : hasSubmitMissingAssets ? "存在缺失素材的镜头，需补齐后才能批量生成" : undefined}
              >
                {busy === "submit" ? "批量生成中..." : "批量生成"}
              </button>
            </div>
          </div>
          <div className="submitSummary">
            <div><small>视频镜头</small><strong>{finalShots.length}</strong></div>
            <div><small>首尾线稿</small><strong>{generatedReferenceImageCount}/{finalShots.length * 2}</strong></div>
            <div><small>视频入队</small><strong>{submitResult?.submitted_count || 0}</strong></div>
            <div><small>阻塞</small><strong>{submitResult?.blocked_count || routeResult?.reference_generation?.blocked_count || 0}</strong></div>
          </div>
          <div className="submitShotList">
            {finalShots.map((shot) => {
              const shotLabel = shotKey(shot);
              const manifest = referenceMap[shotLabel];
              const route = routingShots.find((item) => item.shot_id === shotLabel || item.source_group === shotLabel);
              const hasActiveShotJob = activeVideoShotIds.has(shotLabel);
              const isShotSubmitting = busy === `submit:${shotLabel}` || hasActiveShotJob;
              const hasReferencePair = Boolean(manifest?.entry?.image_url && manifest?.exit?.image_url);
              const missingAssets = submitMissingAssetsByShot[shotLabel] || [];
              const canGenerateShot = Boolean(routeResult?.final_video_plan) && hasReferencePair && missingAssets.length === 0 && !hasActiveShotJob;
              const entryAssetId = manifest?.entry?.asset_id || shot.reference_image_plan?.output_asset_ids?.entry;
              const exitAssetId = manifest?.exit?.asset_id || shot.reference_image_plan?.output_asset_ids?.exit;
              return (
                <article className="submitVideoCard" key={shotLabel}>
                  <header className="submitVideoCardHead">
                    <div>
                      <span>{shotLabel}</span>
                      <strong>{route?.routing_decision?.selected_display_name || shot.model || route?.routing_decision?.selected_model || "未选择模型"}</strong>
                      <small>{route?.routing_decision?.selected_preset || shot.model_params?.resolution_preset || "—"}</small>
                    </div>
                    <div className="submitVideoHeaderActions">
                      <div className="submitVideoActions">
                        <button
                          type="button"
                          className="quiet-button"
                          onClick={() => setRoutingDetailShotId(shotLabel)}
                          disabled={!route}
                        >
                          分析详情
                        </button>
                        <button
                          type="button"
                          className="textButton"
                          onClick={() => void runSubmit(shot)}
                          disabled={Boolean(busy) || !canGenerateShot}
                          title={hasActiveShotJob ? "该分镜已有生成中的视频任务" : missingAssets.length ? `缺少必要素材：${missingAssets.join("、")}` : !hasReferencePair ? "缺少首尾参考帧" : undefined}
                        >
                          {isShotSubmitting ? "生成中..." : "生成"}
                        </button>
                      </div>
                      <b>{shot.duration || route?.duration || 0}s</b>
                    </div>
                  </header>
                  <section className="submitVideoDescription">
                    <div>
                      <small>描述</small>
                      <p>{shot.prompt_zh || "暂无视频生成描述"}</p>
                    </div>
                  </section>
                  <ReferenceFrameSlots
                    shotId={shot.shot_id}
                    manifest={manifest}
                    plan={shot.reference_image_plan}
                    apiBase={API_BASE}
                    isGenerating={busy === "routing" || busy === "references"}
                    uploadProgress={{
                      entry: entryAssetId ? uploadProgress[entryAssetId] : undefined,
                      exit: exitAssetId ? uploadProgress[exitAssetId] : undefined,
                    }}
                    uploadDisabled={Boolean(busy)}
                    onUploadFrame={(role) => void uploadReferenceFrame(shot, role)}
                    compact
                  />
                  <footer>
                    <span>资产 {shot.references?.length || 0}</span>
                    <span>首帧 {manifest?.entry?.asset_id || (manifest?.status === "blocked" ? "失败" : "未生成")}</span>
                    <span>尾帧 {manifest?.exit?.asset_id || (manifest?.status === "blocked" ? "失败" : "未生成")}</span>
                    {missingAssets.length ? <span>缺失 {missingAssets.join("、")}</span> : null}
                  </footer>
                </article>
              );
            })}
          </div>
          {submitResult && <div className="workflowJsonSummary autoBlockedSummary"><div><span>提交结果</span><b>{submitResult.submitted_count || 0}</b></div><pre>{JSON.stringify(submitResult, null, 2)}</pre></div>}
          </section>
          {routingDetailShotId && (
            <div className="routeDetailModalBackdrop">
              <button className="routeDetailModalCloseLayer" type="button" aria-label="关闭路由分析详情" onClick={() => setRoutingDetailShotId(null)} />
              <section className="routeDetailModal" role="dialog" aria-modal="true" aria-label={`${routingDetailShotId} 路由分析详情`}>
                <header>
                  <div>
                    <span>{routingDetailShotId}</span>
                    <h3>路由分析结果</h3>
                    <p>查看该镜头的难度评分、模型路由、选择理由和首尾参考帧。</p>
                  </div>
                  <button type="button" onClick={() => setRoutingDetailShotId(null)}>关闭</button>
                </header>
                <div className="routeDetailModalBody">
                  <RoutingResultPanel
                    routingShots={routingDetailRoute ? [routingDetailRoute] : []}
                    finalShots={routingDetailFinalShot ? [routingDetailFinalShot] : []}
                    references={referenceMap}
                    apiBase={API_BASE}
                    isGenerating={busy === "routing" || busy === "references"}
                  />
                </div>
              </section>
            </div>
          )}
        </section>
      )}

      {activeStep === "compose" && (
        <section className="card autoFullCard">
          <div className="cardHead">
            <div><span>07</span><div><h2>视频合成</h2><p>读取第六步 job 输出里的分镜视频路径，调用 ffmpeg 合并为完整视频。</p></div></div>
            <button
              type="button"
              className="textButton"
              onClick={() => void runCompose()}
              disabled={Boolean(busy) || !canComposeVideos(submitResult)}
              title={!canComposeVideos(submitResult) ? "至少需要 2 个已生成视频才能合成" : undefined}
            >
              {busy === "compose" ? "正在合成..." : "ffmpeg 合成视频"}
            </button>
          </div>
          <div className="submitSummary">
            <div><small>视频任务</small><strong>{submitResult?.jobs?.length || 0}</strong></div>
            <div><small>可合成</small><strong>{composableVideoCount(submitResult)}</strong></div>
            <div><small>合成阻塞</small><strong>{composeResult?.blocked_count || 0}</strong></div>
            <div><small>状态</small><strong>{composeResult?.status || "待合成"}</strong></div>
          </div>
          <div className="submitShotList">
            {(submitResult?.jobs || []).map((job) => {
              const source = videoSrc(job);
              const jobShotId = job.shot_id || "";
              const regenerateShot = finalShots.find((shot) => shotKey(shot) === jobShotId || shot.shot_id === jobShotId || shot.group_id === jobShotId);
              const canRegenerateJob = Boolean(regenerateShot && routeResult?.final_video_plan && !busy);
              const statusLabel = job.status === "succeeded"
                ? "已完成"
                : job.status === "failed" || job.status === "cancelled" || job.status === "blocked"
                  ? "生成失败"
                  : "生成中";
              return (
                <article className={`submitVideoCard videoJob-${job.status || "queued"}`} key={job.job_id || job.shot_id}>
                  <header className="submitVideoCardHead">
                    <div>
                      <span>{job.shot_id || "分镜"}</span>
                      <strong>{job.model || "视频模型"}</strong>
                      <small>{job.provider || "等待提交"}</small>
                    </div>
                    <b>{statusLabel}</b>
                  </header>
                  {job.status === "succeeded" && source ? (
                    <video src={source} controls preload="metadata">
                      <track kind="captions" label="暂无字幕" />
                    </video>
                  ) : job.status === "failed" || job.status === "cancelled" || job.status === "blocked" ? (
                    <div className="videoJobRetryPanel">
                      <p className="videoJobError">{job.error_message || "视频生成失败"}</p>
                      <button
                        type="button"
                        className="textButton"
                        onClick={() => regenerateShot && void runSubmit(regenerateShot)}
                        disabled={!canRegenerateJob}
                        title={canRegenerateJob ? undefined : "需要先加载路由与首尾帧结果后才能重新生成"}
                      >
                        重新生成
                      </button>
                    </div>
                  ) : (
                    <p className="videoJobGenerating">生成中，系统每 10 秒自动查询一次结果…</p>
                  )}
                </article>
              );
            })}
          </div>
          {composeResult?.output_url ? (
            <div className="workflowJsonSummary autoBlockedSummary">
              <div><span>合成完成</span><b>{composeResult.compose_id}</b></div>
              <p>完整成片已保存，请进入第八步“终章”查看和播放。</p>
            </div>
          ) : composeResult ? (
            <div className="workflowJsonSummary autoBlockedSummary"><div><span>合成结果</span><b>{composeResult.status || "blocked"}</b></div><pre>{JSON.stringify(composeResult, null, 2)}</pre></div>
          ) : null}
        </section>
      )}

      {activeStep === "finale" && (
        <section className="card autoFullCard">
          <div className="cardHead">
            <div><span>08</span><div><h2>终章</h2><p>查看 ffmpeg 合成后的完整视频结果。</p></div></div>
            {composeResult?.output_url ? (
              <a className="textButton" href={composeVideoSrc(composeResult)} target="_blank" rel="noreferrer">打开完整视频</a>
            ) : null}
          </div>
          <div className="submitSummary">
            <div><small>合成 ID</small><strong>{composeResult?.compose_id || "未生成"}</strong></div>
            <div><small>合成输入</small><strong>{composeResult?.input_count || 0}</strong></div>
            <div><small>跳过</small><strong>{composeResult?.blocked_count || 0}</strong></div>
            <div><small>状态</small><strong>{composeResult?.status || "待合成"}</strong></div>
          </div>
          {composeResult?.output_url ? (
            <div className="workflowJsonSummary autoBlockedSummary">
              <div><span>完整成片</span><b>{composeResult.compose_id}</b></div>
              <video src={composeVideoSrc(composeResult)} controls preload="metadata">
                <track kind="captions" label="暂无字幕" />
              </video>
              <p>合成结果文件：{composeResult.manifest_path || "manifest.json"}</p>
            </div>
          ) : (
            <div className="emptyState">
              <strong>还没有合成结果</strong>
              <p>请先回到第七步，至少选择 2 个已生成视频后执行 ffmpeg 合成。</p>
            </div>
          )}
        </section>
      )}
        </section>
      </section>
    </main>
  );
}
