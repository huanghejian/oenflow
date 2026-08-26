"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import RoutingResultPanel from "./components/RoutingResultPanel";
import ShotGroupAnalysisPanel from "./components/ShotGroupAnalysisPanel";
import StepTabs from "./components/StepTabs";
import StoryboardAccordion from "./components/StoryboardAccordion";
import type {
  AnalysisResponse,
  AssetItem,
  AssetPromptResponse,
  AssetSplitResponse,
  AssetRecord,
  AutoFlowAssets,
  ComposeResponse,
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
type PromptTemplateName = "asset-split" | "asset-prompts" | "storyboard-split" | "shot-group-analysis";
type AssetPromptFilter = "all" | "characters" | "scenes" | "items";
type PromptVersion = {
  version: string;
  created_at?: string;
  size_bytes?: number;
};
const PROMPT_TEMPLATE_NAMES: PromptTemplateName[] = ["asset-split", "asset-prompts", "storyboard-split", "shot-group-analysis"];
const EMPTY_PROMPT_VERSIONS: Record<PromptTemplateName, PromptVersion[]> = {
  "asset-split": [],
  "asset-prompts": [],
  "storyboard-split": [],
  "shot-group-analysis": [],
};
const EMPTY_SELECTED_PROMPT_VERSIONS: Record<PromptTemplateName, string> = {
  "asset-split": "",
  "asset-prompts": "",
  "storyboard-split": "",
  "shot-group-analysis": "",
};

const FLOW_STEPS: Array<{ id: FlowStep; index: string; title: string; caption: string }> = [
  { id: "split", index: "01", title: "识别资产", caption: "剧本 / 资产清单" },
  { id: "assetPrompts", index: "02", title: "资产提示词", caption: "生资产提示词" },
  { id: "assets", index: "03", title: "拆分镜", caption: "资产 / 分镜提示词" },
  { id: "analysis", index: "04", title: "镜头组分析", caption: "连续拍摄与4秒拼接" },
  { id: "routing", index: "05", title: "路由与首尾帧", caption: "模型评分并行生图" },
  { id: "submit", index: "06", title: "视频生成", caption: "提交分镜视频任务" },
  { id: "compose", index: "07", title: "视频合成", caption: "ffmpeg 合并分镜视频" },
];

const EMPTY_ASSETS: AutoFlowAssets = { characters: [], scenes: [], items: [] };
const DEFAULT_STORYBOARD_PROMPT = `以 Seedance 2.0 分镜导演 Agent 指令系统为基础，只完成分镜结构组织与子镜头规划。
必须基于上一步资产清单引用角色、场景、关键道具，不要新增未识别的核心资产。
按 sbid/segment 组织剧情，每个 segment 必须包含 sub_shots，sub_shots 是后续识别连续拍摄、4秒拼接和独立镜头组的基本单位。
每个子镜头保留 duration、content、scene、characters、items、shot_type、camera_movement、entry_state、performance、exit_state、dialogue、continuity_hint、indivisible。
分镜规划需要遵守：台词不遗漏、角色/道具引用准确、空间状态连续、活态表演、自然语言运镜、光影氛围、景别角度多样性。
最终只返回 ai-video 自动流兼容 JSON，不输出审视过程、检查清单或 markdown。`;
const DEFAULT_ANALYSIS_PROMPT = `请分析相邻子镜头之间的拍摄关系：
1. 哪些子镜头必须连续拍摄、不可分割。
2. 哪些子镜头因为不足最小4秒，需要向后拼接成镜头组。
3. 哪些单个子镜头已满足独立拍摄条件。
同时为每个镜头组输出首帧普通参考图提示词和尾帧编辑提示词。`;
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
  const [activeStep, setActiveStep] = useState<FlowStep>("split");
  const [projectParams, setProjectParams] = useState<ProjectParams>(() => projectDefaults());
  const [assetPrompt, setAssetPrompt] = useState("");
  const [assetPromptGenerationPrompt, setAssetPromptGenerationPrompt] = useState(DEFAULT_ASSET_PROMPT_GENERATION_PROMPT);
  const [storyboardPrompt, setStoryboardPrompt] = useState(DEFAULT_STORYBOARD_PROMPT);
  const [analysisPrompt, setAnalysisPrompt] = useState(DEFAULT_ANALYSIS_PROMPT);
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
  const [assetPromptFilter, setAssetPromptFilter] = useState<AssetPromptFilter>("all");
  const [assetPromptPreviewAsset, setAssetPromptPreviewAsset] = useState<AssetItem | null>(null);
  const [assetPromptPreviewVariant, setAssetPromptPreviewVariant] = useState("");
  const [generationMode, setGenerationMode] = useState<GenerationMode>("demo");
  const [imageModel, setImageModel] = useState("openai/gpt-image-2");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const assets = splitResult?.assets || assetPromptResult?.assets || assetResult?.assets || EMPTY_ASSETS;
  const storyContext = splitResult?.story_context || assetPromptResult?.story_context || assetResult?.story_context || {};
  const segments = splitResult?.segments || [];
  const shotGroups = analysisResult?.shot_groups || [];
  const routingShots = routeResult?.routing_analysis?.shots || [];
  const finalShots = routeResult?.final_video_plan?.shots || [];
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
  const readyAssetCount = assetPromptCards.filter((item) => assetRegistry[item.asset.id]).length;
  const referenceMap = useMemo(() => {
    const map: Record<string, ReferenceManifest> = {};
    for (const manifest of routeResult?.reference_generation?.completed || []) {
      if (manifest.shot_id) map[manifest.shot_id] = manifest;
    }
    return map;
  }, [routeResult]);
  const completedSteps = useMemo(() => {
    const done = new Set<FlowStep>();
    if (assetResult) done.add("split");
    if (assetPromptResult) done.add("assetPrompts");
    if (splitResult) done.add("assets");
    if (analysisResult) done.add("analysis");
    if (routeResult) done.add("routing");
    if (submitResult) done.add("submit");
    if (composeResult) done.add("compose");
    return done;
  }, [analysisResult, assetPromptResult, assetResult, composeResult, routeResult, splitResult, submitResult]);
  const currentStepIndex = Math.max(0, FLOW_STEPS.findIndex((step) => step.id === activeStep));
  const currentStep = FLOW_STEPS[currentStepIndex] || FLOW_STEPS[0];
  const progressPercent = ((currentStepIndex + 1) / FLOW_STEPS.length) * 100;

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const response = await fetch(`${API_BASE}/health`, { cache: "no-store" });
        const data = await readJson<{ ok?: boolean; reference_image_provider_available?: boolean }>(response);
        if (cancelled) return;
        setBackendOnline(Boolean(response.ok && data.ok));
      } catch {
        if (!cancelled) setBackendOnline(false);
      }
    }
    async function loadPromptTemplates() {
      try {
        const [assetSplit, assetPrompts, storyboardSplit, shotGroupAnalysis] = await Promise.all([
          loadPromptTemplate("asset-split", ""),
          loadPromptTemplate("asset-prompts", DEFAULT_ASSET_PROMPT_GENERATION_PROMPT),
          loadPromptTemplate("storyboard-split", DEFAULT_STORYBOARD_PROMPT),
          loadPromptTemplate("shot-group-analysis", DEFAULT_ANALYSIS_PROMPT),
        ]);
        if (cancelled) return;
        setAssetPrompt(assetSplit);
        setAssetPromptGenerationPrompt(assetPrompts);
        setStoryboardPrompt(storyboardSplit);
        setAnalysisPrompt(shotGroupAnalysis);
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

  async function uploadAsset(assetId: string, file: File) {
    resetMessages();
    setBusy(`upload:${assetId}`);
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/assets/upload?asset_id=${encodeURIComponent(assetId)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
        body: file,
      });
      const data = await readJson<AssetRecord & { detail?: string }>(response);
      if (!response.ok) throw new Error(data.detail || "上传图片失败");
      await refreshAssetRegistry();
      setNotice(`${assetId} 已绑定到 ${file.name}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "上传图片失败");
    } finally {
      setBusy("");
    }
  }

  async function runAnalysis() {
    if (!splitResult) return;
    resetMessages();
    setBusy("analysis");
    setAnalysisResult(null);
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
          use_ai: true,
        }),
      });
      const data = await readJson<AnalysisResponse>(response);
      if (!response.ok) throw new Error(data.detail || "镜头组分析失败");
      setAnalysisResult(data);
      setActiveStep("routing");
      setNotice(`分析完成：形成 ${data.shot_groups.length} 个镜头组。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "镜头组分析失败");
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
      setNotice(`已加载最近镜头组分析结果：${data.shot_groups.length} 个镜头组，可继续路由与首尾帧。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "加载最近镜头组分析结果失败");
    } finally {
      setBusy("");
    }
  }

  async function runRoutingAndReferences() {
    if (!splitResult || !analysisResult) return;
    resetMessages();
    setBusy("routing");
    setRouteResult(null);
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/route-and-generate-refs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_params: projectParams,
          assets,
          story_context: splitResult.story_context,
          shot_groups: shotGroups,
          generation_mode: generationMode,
          image_model: generationMode === "provider" ? imageModel : undefined,
        }),
      });
      const data = await readJson<RouteResponse>(response);
      if (!response.ok) throw new Error(data.detail || "路由或首尾帧生成失败");
      setRouteResult(data);
      await refreshAssetRegistry();
      setActiveStep("submit");
      setNotice(`路由完成：${data.final_video_plan?.shots?.length || 0} 个视频镜头；首尾帧完成 ${data.reference_generation?.completed_count || 0}，阻塞 ${data.reference_generation?.blocked_count || 0}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "路由或首尾帧生成失败");
    } finally {
      setBusy("");
    }
  }

  async function runSubmit() {
    if (!routeResult?.final_video_plan) return;
    resetMessages();
    setBusy("submit");
    setSubmitResult(null);
    setComposeResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/autoflow/video/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_params: projectParams, final_video_plan: routeResult.final_video_plan }),
      });
      const data = await readJson<SubmitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "视频任务提交失败");
      setSubmitResult(data);
      setActiveStep("compose");
      setNotice(`视频任务提交完成：入队 ${data.submitted_count || 0}，阻塞 ${data.blocked_count || 0}。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "视频任务提交失败");
    } finally {
      setBusy("");
    }
  }

  async function runCompose() {
    if (!submitResult?.jobs?.length) return;
    resetMessages();
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
      setNotice(data.output_url ? `视频合成完成：${data.input_count || 0} 个分镜已合并。` : data.message || "没有可合成的视频文件。");
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
            <span className={backendOnline ? "save-state online-state" : "save-state offline-state"}><i />{backendOnline === null ? "连接中" : backendOnline ? "后端已就绪" : "后端未连接"}</span>
            <button className="quiet-button" type="button" onClick={() => void refreshAssetRegistry()} disabled={Boolean(busy)}>刷新资产</button>
            <button className="avatar" aria-label="用户菜单" type="button">OF</button>
          </div>
        </header>

        <div className="progress-strip"><span style={{ width: `${progressPercent}%` }} /></div>

        <section className="page-wrap autoFlowContent">
          {activeStep !== "assetPrompts" && (
            <div className="page-head autoPageHead">
              <div>
                <span>{currentStep.index}</span>
                <div>
                  <p>AI-VIDEO COMPATIBLE WORKFLOW</p>
                  <h2>{currentStep.title}</h2>
                </div>
              </div>
              <div className="page-head-actions autoHeroStats">
                <span><b>{segments.length}</b> 分镜</span>
                <span><b>{shotGroups.length}</b> 镜头组</span>
                <span><b>{finalShots.length}</b> 视频镜头</span>
              </div>
            </div>
          )}

          {activeStep !== "assetPrompts" && (error || notice) && <div className={error ? "message error autoMessage" : "message success autoMessage"}>{error || notice}</div>}

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
              return (
                <article className={record ? "assetCenterCard bound" : "assetCenterCard"} key={`${key}:${asset.id}`}>
                  <div className="assetCenterPreview">
                    <b>{label}</b>
                    {record?.url ? <div className="assetCenterImage" style={{ backgroundImage: `url(${API_BASE}${record.url})` }} aria-label={asset.name} /> : <span>{glyph}</span>}
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
              return (
                <article className={record ? "assetCenterCard bound" : "assetCenterCard"} key={`storyboard:${key}:${asset.id}`}>
                  <div className="assetCenterPreview">
                    <b>{label}</b>
                    {record?.url ? <div className="assetCenterImage" style={{ backgroundImage: `url(${API_BASE}${record.url})` }} aria-label={asset.name} /> : <span>{glyph}</span>}
                    <small>{record ? "素材已绑定" : "等待素材"}</small>
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
                      <span>{uploading ? "上传中" : record ? "替换图片" : "上传图片"}</span>
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
        <section className="autoStepGrid analysisGrid">
          <section className="card">
            <div className="cardHead">
              <div><span>04</span><div><h2>分析镜头组提示词</h2><p>识别连续拍摄、4秒拼接与独立镜头组。</p></div></div>
            </div>
            <label className="autoField analysisPrompt">
              {renderPromptLabel("shot-group-analysis", "分析提示词")}
              <textarea value={analysisPrompt} onChange={(event) => setPromptTemplateContent("shot-group-analysis", event.target.value)} />
            </label>
            <button className="generateButton autoPrimaryButton" type="button" onClick={() => void runAnalysis()} disabled={Boolean(busy) || !splitResult}>
              <span>{busy === "analysis" ? "正在分析镜头组..." : "分析镜头组"}</span><b>→</b>
            </button>
            <button className="textButton" type="button" onClick={() => void loadLatestAnalysis()} disabled={Boolean(busy) || backendOnline !== true}>
              {busy === "analysis-load" ? "正在加载..." : "加载最近镜头组分析"}
            </button>
            <ShotGroupAnalysisPanel groups={shotGroups} />
          </section>
          <section className="card">
            <div className="cardHead">
              <div><span>分镜</span><div><h2>分镜与子镜头</h2><p>展开分镜后可继续展开每个子镜头。</p></div></div>
            </div>
            <StoryboardAccordion segments={segments as Segment[]} />
          </section>
        </section>
      )}

      {activeStep === "routing" && (
        <section className="card autoFullCard">
          <div className="cardHead">
            <div><span>05</span><div><h2>路由评分与首尾帧</h2><p>按第四步镜头组执行模型路由，并并行生成首帧和尾帧图片。</p></div></div>
            <div className="autoInlineActions">
              <select value={generationMode} onChange={(event) => setGenerationMode(event.target.value as GenerationMode)}>
                <option value="demo">Demo 占位图</option>
                <option value="provider">真实图片模型</option>
              </select>
              <input value={imageModel} onChange={(event) => setImageModel(event.target.value)} disabled={generationMode !== "provider"} />
              <button type="button" className="textButton" onClick={() => void runRoutingAndReferences()} disabled={Boolean(busy) || !analysisResult}>
                {busy === "routing" ? "路由与生图中..." : "执行路由 + 首尾帧"}
              </button>
            </div>
          </div>
          <RoutingResultPanel routingShots={routingShots} finalShots={finalShots} references={referenceMap} apiBase={API_BASE} />
          {routeResult?.reference_generation?.blocked?.length ? (
            <div className="workflowJsonSummary autoBlockedSummary">
              <div><span>首尾帧阻塞</span><b>{routeResult.reference_generation.blocked_count || 0}</b></div>
              <pre>{JSON.stringify(routeResult.reference_generation.blocked, null, 2)}</pre>
            </div>
          ) : null}
        </section>
      )}

      {activeStep === "submit" && (
        <section className="card autoFullCard">
          <div className="cardHead">
            <div><span>06</span><div><h2>视频生成</h2><p>提交镜头组路由方案、首尾帧图片、资产图片和分镜提示词，等待每个分镜视频输出。</p></div></div>
            <button type="button" className="textButton" onClick={() => void runSubmit()} disabled={Boolean(busy) || !routeResult?.final_video_plan}>
              {busy === "submit" ? "正在提交..." : "提交生成视频"}
            </button>
          </div>
          <div className="submitSummary">
            <div><small>视频镜头</small><strong>{finalShots.length}</strong></div>
            <div><small>首尾帧完成</small><strong>{routeResult?.reference_generation?.completed_count || 0}</strong></div>
            <div><small>视频入队</small><strong>{submitResult?.submitted_count || 0}</strong></div>
            <div><small>阻塞</small><strong>{submitResult?.blocked_count || routeResult?.reference_generation?.blocked_count || 0}</strong></div>
          </div>
          <div className="submitShotList">
            {finalShots.map((shot) => {
              const manifest = shot.shot_id ? referenceMap[shot.shot_id] : undefined;
              return (
                <article key={shot.shot_id}>
                  <header>
                    <strong>{shot.shot_id}</strong>
                    <span>{shot.model} · {shot.model_params?.resolution_preset}</span>
                    <b>{shot.duration}s</b>
                  </header>
                  <p>{shot.prompt_zh}</p>
                  <footer>
                    <span>资产 {shot.references?.length || 0}</span>
                    <span>首帧 {manifest?.entry?.asset_id || "未生成"}</span>
                    <span>尾帧 {manifest?.exit?.asset_id || "未生成"}</span>
                  </footer>
                </article>
              );
            })}
          </div>
          {submitResult && <div className="workflowJsonSummary autoBlockedSummary"><div><span>提交结果</span><b>{submitResult.submitted_count || 0}</b></div><pre>{JSON.stringify(submitResult, null, 2)}</pre></div>}
        </section>
      )}

      {activeStep === "compose" && (
        <section className="card autoFullCard">
          <div className="cardHead">
            <div><span>07</span><div><h2>视频合成</h2><p>读取第六步 job 输出里的分镜视频路径，调用 ffmpeg 合并为完整视频。</p></div></div>
            <button type="button" className="textButton" onClick={() => void runCompose()} disabled={Boolean(busy) || !submitResult?.jobs?.length}>
              {busy === "compose" ? "正在合成..." : "ffmpeg 合成视频"}
            </button>
          </div>
          <div className="submitSummary">
            <div><small>视频任务</small><strong>{submitResult?.jobs?.length || 0}</strong></div>
            <div><small>合成输入</small><strong>{composeResult?.input_count || 0}</strong></div>
            <div><small>合成阻塞</small><strong>{composeResult?.blocked_count || 0}</strong></div>
            <div><small>状态</small><strong>{composeResult?.status || "待合成"}</strong></div>
          </div>
          {composeResult?.output_url ? (
            <div className="workflowJsonSummary autoBlockedSummary">
              <div><span>合成视频</span><b>{composeResult.compose_id}</b></div>
              <video src={`${API_BASE}${composeResult.output_url}`} controls>
                <track kind="captions" label="暂无字幕" />
              </video>
              <a href={`${API_BASE}${composeResult.output_url}`} target="_blank" rel="noreferrer">打开合成视频</a>
            </div>
          ) : null}
          {composeResult && <div className="workflowJsonSummary autoBlockedSummary"><div><span>合成结果</span><b>{composeResult.status || "blocked"}</b></div><pre>{JSON.stringify(composeResult, null, 2)}</pre></div>}
        </section>
      )}
        </section>
      </section>
    </main>
  );
}
