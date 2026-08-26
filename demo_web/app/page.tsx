"use client";
/* eslint-disable @next/next/no-img-element */

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";

type RoutingTier = "low" | "medium" | "high";
type PromptInfo = { prompt: string; provider?: string; model?: string | null; reasoning_effort?: string | null; internal_output_format?: string | null };
type AtomicShot = {
  atomic_id?: string; scene_asset?: string; story_priority?: string; narrative_class?: string;
  narrative_function?: string; atomic_duration?: number;
  continuity?: { entry?: string; exit?: string; los?: string };
  prompt_core?: { timeline_local?: string; guardrail?: string };
};
type DirectorPlan = {
  routing_tier?: string; aspect_ratio?: string;
  asset_catalog?: { scenes?: string[]; roles?: string[]; props?: string[] };
  scene_contexts?: unknown[]; atomic_shots?: AtomicShot[];
};
type DirectorResponse = {
  director_plan: DirectorPlan;
  llm?: { response_id?: string; provider?: string; model?: string; usage?: Record<string, number>; finish_reason?: string };
};
type RoutingCandidate = {
  model?: string; preset?: string; qualified?: boolean; selected?: boolean;
  fit_quality?: number; reliability?: number; call_points?: number;
  expected_usable_points?: number; tier_score?: number;
  hard_reasons?: string[]; margins?: Record<string, number>;
};
type RoutingDecision = {
  tier?: RoutingTier; selected_model?: string; selected_display_name?: string;
  selected_preset?: string; fit_quality?: number; reliability?: number;
  call_points?: number; expected_usable_points?: number;
  medium_target_quality?: number; medium_reliability_floor?: number;
  medium_target_met?: boolean; medium_selection_mode?: string;
  candidates?: RoutingCandidate[];
};
type RoutingShot = {
  shot_id?: string; atomic_ids?: string[]; duration?: number;
  routing_requirements?: Record<string, string>;
  routing_decision: RoutingDecision;
};
type FinalShot = {
  shot_id?: string; atomic_ids?: string[]; model?: string; duration?: number;
  model_params?: { resolution_preset?: string }; prompt_zh?: string;
  references?: Array<{ asset_id?: string; media_type?: string; required?: boolean; derived?: boolean; purpose?: string }>;
  reference_image_plan?: {
    input_asset_ids?: string[];
    output_asset_ids?: { entry?: string; exit?: string };
    entry_state_reference_prompt_zh?: string;
    exit_state_reference_edit_prompt_zh?: string;
  };
};
type CompileResponse = {
  routing_analysis?: { tier?: RoutingTier; shots?: RoutingShot[] };
  final_video_plan?: { shots?: FinalShot[] };
  validation?: { ok?: boolean };
  detail?: string;
};
type DemoCase = { input?: {
  episode_id: string; project_type: string; aspect_ratio: string; resolution: string;
  global_visual_lock: string; feedback: string; registered_assets: unknown; script: string;
}; director_plan?: DirectorPlan; llm?: DirectorResponse["llm"] };
type DebugStage = "director" | "spatial" | "packer" | "router" | "compiler" | "validator";
type DebugResponse = {
  stage: DebugStage; title: string; description: string; tier: RoutingTier;
  input_artifact: string; output_artifact: string; output_size_bytes: number;
  summary: Record<string, string | number | boolean | null>;
  preview: Record<string, unknown>; download_url: string; detail?: string;
};
type WorkflowStep = "assets" | "references" | "binding" | "submit";
type AssetRecord = {
  asset_id?: string; file_id?: string; url?: string; source?: string;
  original_filename?: string; size_bytes?: number; binding_status?: string;
};
type AssetRegistryResponse = { count?: number; assets?: Record<string, AssetRecord>; detail?: string };
type ReferenceManifest = {
  job_id?: string; shot_id?: string; status?: string; demo_placeholder?: boolean; message?: string;
  generation_mode?: string; image_model?: string; prompt_source?: string; usage?: Record<string, unknown>;
  entry?: { asset_id?: string; image_url?: string; prompt_zh?: string; status?: string };
  exit?: { asset_id?: string; image_url?: string; prompt_zh?: string; status?: string };
};
type ReferenceBulkResponse = {
  completed_count?: number; blocked_count?: number; completed?: ReferenceManifest[];
  blocked?: Array<{ shot_id?: string; missing_asset_ids?: string[]; detail?: string }>; detail?: string;
};
type BindingResponse = {
  ready_count?: number; blocked_count?: number; registry_count?: number;
  ready?: Array<Record<string, unknown>>;
  blocked?: Array<{ shot_id?: string; missing_required_asset_ids?: string[]; missing_derived_reference_ids?: string[] }>;
  detail?: string;
};
type SubmitResponse = {
  submitted_count?: number; blocked_count?: number; registry_count?: number; mode?: string;
  jobs?: Array<{ job_id?: string; shot_id?: string; status?: string; bound_asset_ids?: string[]; derived_reference_ids?: string[] }>;
  blocked?: BindingResponse["blocked"]; detail?: string;
};
type ImageGenerationConfig = {
  provider?: string; configured?: boolean; model?: string; resolution?: string;
  quality?: string; aspect_ratio?: string; prompt_source?: string; detail?: string;
};

const DEBUG_STAGES: Array<{ id: DebugStage; index: string; label: string }> = [
  { id: "director", index: "A", label: "导演输出" },
  { id: "spatial", index: "01", label: "空间校验" },
  { id: "packer", index: "02", label: "分镜打包" },
  { id: "router", index: "03", label: "模型路由" },
  { id: "compiler", index: "04", label: "提示词编译" },
  { id: "validator", index: "05", label: "最终验收" },
];

const WORKFLOW_STEPS: Array<{ id: WorkflowStep; index: string; label: string }> = [
  { id: "assets", index: "06", label: "图片资产" },
  { id: "references", index: "07", label: "站位图" },
  { id: "binding", index: "08", label: "自动绑定" },
  { id: "submit", index: "09", label: "视频提交" },
];

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

function saveFile(name: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: "application/json;charset=utf-8" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) return {} as T;
  try { return JSON.parse(text) as T; }
  catch { throw new Error(`服务返回了无法解析的内容（HTTP ${response.status}）`); }
}

export default function Home() {
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [demoAvailable, setDemoAvailable] = useState(false);
  const [promptInfo, setPromptInfo] = useState<PromptInfo | null>(null);
  const [directorPrompt, setDirectorPrompt] = useState("");
  const [episodeId, setEpisodeId] = useState("EP001");
  const [projectType, setProjectType] = useState("短剧");
  const [aspectRatio, setAspectRatio] = useState("9:16");
  const [resolution, setResolution] = useState("720P");
  const [tier, setTier] = useState<RoutingTier>("medium");
  const [continuityTracking, setContinuityTracking] = useState(true);
  const [visualLock, setVisualLock] = useState("东方玄幻真人短剧，冷青灰电影质感");
  const [feedback, setFeedback] = useState("");
  const [assetsText, setAssetsText] = useState('{\n  "scenes": [],\n  "roles": [],\n  "props": []\n}');
  const [continuityText, setContinuityText] = useState("{}");
  const [script, setScript] = useState("");
  const [result, setResult] = useState<DirectorResponse | null>(null);
  const [compiled, setCompiled] = useState<CompileResponse | null>(null);
  const [running, setRunning] = useState(false);
  const [phase, setPhase] = useState<"director" | "routing">("director");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [resultMode, setResultMode] = useState<"overview" | "json">("overview");
  const [debugStage, setDebugStage] = useState<DebugStage | null>(null);
  const [debugResult, setDebugResult] = useState<DebugResponse | null>(null);
  const [debugLoading, setDebugLoading] = useState(false);
  const [debugError, setDebugError] = useState("");
  const [workflowStep, setWorkflowStep] = useState<WorkflowStep>("assets");
  const [assetRegistry, setAssetRegistry] = useState<Record<string, AssetRecord>>({});
  const [selectedWorkflowShotId, setSelectedWorkflowShotId] = useState("");
  const [referenceManifests, setReferenceManifests] = useState<Record<string, ReferenceManifest>>({});
  const [referenceBulk, setReferenceBulk] = useState<ReferenceBulkResponse | null>(null);
  const [bindingResult, setBindingResult] = useState<BindingResponse | null>(null);
  const [submitResult, setSubmitResult] = useState<SubmitResponse | null>(null);
  const [workflowBusy, setWorkflowBusy] = useState("");
  const [workflowError, setWorkflowError] = useState("");
  const [workflowNotice, setWorkflowNotice] = useState("");
  const [imageGenerationConfig, setImageGenerationConfig] = useState<ImageGenerationConfig | null>(null);
  const [imageGenerationMode, setImageGenerationMode] = useState<"demo" | "provider">("demo");
  const [imageModel, setImageModel] = useState("openai/gpt-image-2");

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const [healthResponse, promptResponse, imageConfigResponse] = await Promise.all([
          fetch(`${API_BASE}/health`, { cache: "no-store" }),
          fetch(`${API_BASE}/v1/director-prompt`, { cache: "no-store" }),
          fetch(`${API_BASE}/v1/workflow/image-generation`, { cache: "no-store" }),
        ]);
        const health = await readJson<{ ok?: boolean; demo_available?: boolean }>(healthResponse);
        const prompt = await readJson<PromptInfo & { detail?: string }>(promptResponse);
        const imageConfig = await readJson<ImageGenerationConfig>(imageConfigResponse);
        if (!healthResponse.ok) throw new Error("后端健康检查失败");
        if (!promptResponse.ok) throw new Error(prompt.detail || "默认 Prompt 读取失败");
        if (cancelled) return;
        setBackendOnline(Boolean(health.ok));
        setDemoAvailable(Boolean(health.demo_available));
        setPromptInfo(prompt);
        setDirectorPrompt(prompt.prompt);
        if (imageConfigResponse.ok) {
          setImageGenerationConfig(imageConfig);
          setImageModel(imageConfig.model || "openai/gpt-image-2");
        }
      } catch (caught) {
        if (cancelled) return;
        setBackendOnline(false);
        setError(caught instanceof Error ? caught.message : "无法连接本地后端");
      }
    }
    void bootstrap();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const shots = useMemo(() => result?.director_plan.atomic_shots || [], [result]);
  const totalDuration = useMemo(() => shots.reduce((sum, shot) => sum + (shot.atomic_duration || 0), 0), [shots]);
  const jsonOutput = useMemo(() => result ? JSON.stringify(result.director_plan, null, 2) : "", [result]);
  const finalById = useMemo(() => {
    const map = new Map<string, FinalShot>();
    for (const shot of compiled?.final_video_plan?.shots || []) {
      if (shot.shot_id) map.set(shot.shot_id, shot);
    }
    return map;
  }, [compiled]);
  const routingByAtomic = useMemo(() => {
    const map = new Map<string, RoutingShot>();
    for (const route of compiled?.routing_analysis?.shots || []) {
      for (const atomicId of route.atomic_ids || []) map.set(atomicId, route);
    }
    return map;
  }, [compiled]);
  const finalShots = useMemo(() => compiled?.final_video_plan?.shots || [], [compiled]);
  const selectedWorkflowShot = useMemo(
    () => finalShots.find((shot) => shot.shot_id === selectedWorkflowShotId) || finalShots[0],
    [finalShots, selectedWorkflowShotId],
  );
  const selectedReferenceManifest = selectedWorkflowShot?.shot_id
    ? referenceManifests[selectedWorkflowShot.shot_id]
    : undefined;
  const workflowAssets = useMemo(() => {
    const assets = new Map<string, { asset_id: string; required: boolean; usedBy: string[] }>();
    for (const shot of finalShots) {
      for (const reference of shot.references || []) {
        if (!reference.asset_id || reference.derived || reference.media_type !== "image") continue;
        const current = assets.get(reference.asset_id) || { asset_id: reference.asset_id, required: false, usedBy: [] };
        current.required = current.required || Boolean(reference.required);
        if (shot.shot_id && !current.usedBy.includes(shot.shot_id)) current.usedBy.push(shot.shot_id);
        assets.set(reference.asset_id, current);
      }
    }
    return [...assets.values()].sort((a, b) => Number(b.required) - Number(a.required) || a.asset_id.localeCompare(b.asset_id, "zh-CN"));
  }, [finalShots]);

  useEffect(() => {
    if (!finalShots.length) return;
    void refreshAssetRegistry();
  }, [finalShots]);

  function selectedReason(decision: RoutingDecision): string {
    if (decision.tier === "medium" && decision.medium_target_met) {
      return `质量 ${decision.fit_quality?.toFixed(2)} ≥ 目标 ${decision.medium_target_quality?.toFixed(2)}，可靠性 ${((decision.reliability || 0) * 100).toFixed(1)}% ≥ ${((decision.medium_reliability_floor || 0) * 100).toFixed(1)}%；按 Minimum Sufficient 选择满足门槛后的预计可用积分最优方案。`;
    }
    if (decision.tier === "low") {
      return `该候选通过接口硬准入并满足 LOW 质量底线，按最低预计可用积分与 LOW 模型梯队胜出。`;
    }
    if (decision.tier === "high") {
      return `该候选进入近最佳质量窗口，并在画质、可靠性与积分护栏的综合比较中胜出。`;
    }
    return "该候选通过硬准入，并在当前档位的确定性评分与成本规则中胜出。";
  }

  function candidateReason(candidate: RoutingCandidate): string {
    if (candidate.selected) return "已选：当前档位策略胜出";
    if (!candidate.qualified) return candidate.hard_reasons?.join("；") || "未通过接口硬准入";
    return "合格，但质量门槛、可靠性或积分排序未胜出";
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(""); setNotice("");
    setRunning(true); setPhase("director"); setElapsed(0); setResult(null); setCompiled(null);
    try {
      const response = await fetch(`${API_BASE}/v1/demo/sample`, { cache: "no-store" });
      const data = await readJson<DemoCase & { detail?: string }>(response);
      if (!response.ok || !data.director_plan) throw new Error(data.detail || "内置 Demo A 阶段数据不可用");
      setResult({ director_plan: data.director_plan, llm: data.llm }); setResultMode("overview");
      setNotice("已加载内置 A 阶段 Demo，本次没有调用 OpenRouter。点击“下一步”查看拼接提示词与评分。");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Demo 数据加载失败"); }
    finally { setRunning(false); }
  }

  async function compileNext() {
    if (!result) return;
    setError(""); setNotice(""); setRunning(true); setPhase("routing"); setElapsed(0);
    try {
      const compileResponse = await fetch(`${API_BASE}/v1/demo/tier/${tier}`, { cache: "no-store" });
      const compileData = await readJson<CompileResponse>(compileResponse);
      if (!compileResponse.ok) throw new Error(compileData.detail || `Demo 评分数据加载失败（HTTP ${compileResponse.status}）`);
      setCompiled(compileData);
      setSelectedWorkflowShotId(compileData.final_video_plan?.shots?.[0]?.shot_id || "");
      setReferenceBulk(null); setBindingResult(null); setSubmitResult(null);
      setResultMode("overview");
      setNotice(`已加载内置 ${tier.toUpperCase()} 档拼接提示词与候选评分。`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Demo 评分加载失败"); }
    finally { setRunning(false); }
  }

  async function loadDemoInput() {
    setError(""); setNotice("");
    try {
      const response = await fetch(`${API_BASE}/v1/demo/sample`, { cache: "no-store" });
      const data = await readJson<DemoCase & { detail?: string }>(response);
      if (!response.ok || !data.input) throw new Error(data.detail || "演示输入不可用");
      setEpisodeId(data.input.episode_id); setProjectType(data.input.project_type);
      setAspectRatio(data.input.aspect_ratio); setResolution(data.input.resolution);
      setVisualLock(data.input.global_visual_lock); setFeedback(data.input.feedback);
      setAssetsText(JSON.stringify(data.input.registered_assets, null, 2)); setScript(data.input.script);
      setNotice("已载入演示资产和剧本；后续按钮只读取本地 Demo，不调用 OpenRouter。");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "演示输入加载失败"); }
  }

  async function copyResult() {
    try { await navigator.clipboard.writeText(jsonOutput); setNotice("A 阶段 JSON 已复制。"); }
    catch { setError("复制失败，请在原始 JSON 视图中手动选择。"); }
  }

  async function copyPrompt(prompt: string) {
    try { await navigator.clipboard.writeText(prompt); setNotice("完整 prompt_zh 已复制。"); }
    catch { setError("复制失败，请手动选择提示词文本。"); }
  }

  async function loadDebugStage(stage: DebugStage) {
    setDebugStage(stage); setDebugResult(null); setDebugError(""); setDebugLoading(true);
    try {
      const response = await fetch(`${API_BASE}/v1/demo/debug/${stage}?tier=${tier}`, { cache: "no-store" });
      const data = await readJson<DebugResponse>(response);
      if (!response.ok) throw new Error(data.detail || `调试环节加载失败（HTTP ${response.status}）`);
      setDebugResult(data);
    } catch (caught) {
      setDebugError(caught instanceof Error ? caught.message : "调试环节加载失败");
    } finally { setDebugLoading(false); }
  }

  async function refreshAssetRegistry() {
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/assets`, { cache: "no-store" });
      const data = await readJson<AssetRegistryResponse>(response);
      if (!response.ok) throw new Error(data.detail || "资产登记表读取失败");
      setAssetRegistry(data.assets || {});
    } catch (caught) {
      setWorkflowError(caught instanceof Error ? caught.message : "资产登记表读取失败");
    }
  }

  function resetWorkflowMessage() {
    setWorkflowError("");
    setWorkflowNotice("");
  }

  async function seedWorkflowAssets() {
    resetWorkflowMessage(); setWorkflowBusy("seed");
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/assets/seed-demo`, { method: "POST" });
      const data = await readJson<{ seeded_count?: number; detail?: string }>(response);
      if (!response.ok) throw new Error(data.detail || "内置资产登记失败");
      await refreshAssetRegistry();
      setWorkflowNotice(`已登记 ${data.seeded_count || 0} 张内置图片资产，可继续逐镜生成站位图。`);
    } catch (caught) { setWorkflowError(caught instanceof Error ? caught.message : "内置资产登记失败"); }
    finally { setWorkflowBusy(""); }
  }

  async function uploadWorkflowAsset(assetId: string, file: File) {
    resetWorkflowMessage(); setWorkflowBusy(`upload:${assetId}`);
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/assets/upload?asset_id=${encodeURIComponent(assetId)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
        body: file,
      });
      const data = await readJson<AssetRecord & { detail?: string }>(response);
      if (!response.ok) throw new Error(data.detail || `上传失败（HTTP ${response.status}）`);
      await refreshAssetRegistry();
      setWorkflowNotice(`“${assetId}”已绑定到 ${file.name}。`);
    } catch (caught) { setWorkflowError(caught instanceof Error ? caught.message : "图片上传失败"); }
    finally { setWorkflowBusy(""); }
  }

  async function generateReferenceShot() {
    if (!selectedWorkflowShot) return;
    resetWorkflowMessage(); setWorkflowBusy("reference-one");
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/reference-images/generate-shot`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          episode_id: episodeId,
          shot: selectedWorkflowShot,
          demo_case: imageGenerationMode === "demo",
          generation_mode: imageGenerationMode,
          image_model: imageGenerationMode === "provider" ? imageModel : undefined,
        }),
      });
      const data = await readJson<ReferenceManifest & { detail?: string }>(response);
      if (!response.ok) throw new Error(data.detail || "站位图生成失败");
      if (data.shot_id) setReferenceManifests((current) => ({ ...current, [data.shot_id || ""]: data }));
      await refreshAssetRegistry();
      setWorkflowNotice(imageGenerationMode === "provider"
        ? `${data.shot_id} 已用分镜 JSON 提示词调用 ${imageModel}，开始/结束站位图已生成并登记。`
        : `${data.shot_id} 的 Demo 占位站位图已登记。`);
    } catch (caught) { setWorkflowError(caught instanceof Error ? caught.message : "站位图生成失败"); }
    finally { setWorkflowBusy(""); }
  }

  async function generateAllReferenceShots() {
    if (!compiled?.final_video_plan) return;
    resetWorkflowMessage(); setWorkflowBusy("reference-all"); setReferenceBulk(null);
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/reference-images/generate-all`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ episode_id: episodeId, final_video_plan: compiled.final_video_plan }),
      });
      const data = await readJson<ReferenceBulkResponse>(response);
      if (!response.ok) throw new Error(data.detail || "批量站位图生成失败");
      setReferenceBulk(data);
      const indexed: Record<string, ReferenceManifest> = {};
      for (const manifest of data.completed || []) if (manifest.shot_id) indexed[manifest.shot_id] = manifest;
      setReferenceManifests((current) => ({ ...current, ...indexed }));
      await refreshAssetRegistry();
      setWorkflowNotice(`站位图完成 ${data.completed_count || 0} 镜，阻塞 ${data.blocked_count || 0} 镜。`);
    } catch (caught) { setWorkflowError(caught instanceof Error ? caught.message : "批量站位图生成失败"); }
    finally { setWorkflowBusy(""); }
  }

  async function runAutoBinding() {
    if (!compiled?.final_video_plan) return;
    resetWorkflowMessage(); setWorkflowBusy("binding"); setBindingResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/bind`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ episode_id: episodeId, final_video_plan: compiled.final_video_plan }),
      });
      const data = await readJson<BindingResponse>(response);
      if (!response.ok) throw new Error(data.detail || "资产绑定失败");
      setBindingResult(data);
      setWorkflowNotice(`自动绑定完成：可提交 ${data.ready_count || 0} 镜，阻塞 ${data.blocked_count || 0} 镜。`);
    } catch (caught) { setWorkflowError(caught instanceof Error ? caught.message : "资产绑定失败"); }
    finally { setWorkflowBusy(""); }
  }

  async function submitVideoJobs() {
    if (!compiled?.final_video_plan) return;
    resetWorkflowMessage(); setWorkflowBusy("submit"); setSubmitResult(null);
    try {
      const response = await fetch(`${API_BASE}/v1/workflow/video/submit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ episode_id: episodeId, final_video_plan: compiled.final_video_plan }),
      });
      const data = await readJson<SubmitResponse>(response);
      if (!response.ok) throw new Error(data.detail || "视频任务提交失败");
      setSubmitResult(data);
      setWorkflowNotice(`已将 ${data.submitted_count || 0} 镜加入本地视频生成模拟队列；阻塞 ${data.blocked_count || 0} 镜。`);
    } catch (caught) { setWorkflowError(caught instanceof Error ? caught.message : "视频任务提交失败"); }
    finally { setWorkflowBusy(""); }
  }

  return <main className="appShell">
    <header className="topbar">
      <div className="brand"><span className="brandMark">A</span><div><strong>镜序 · 导演台</strong><small>SHORT DRAMA DIRECTOR</small></div></div>
      <div className="runtimeStatus"><span className={backendOnline ? "statusDot online" : "statusDot"} /><div><strong>{backendOnline === null ? "正在连接" : backendOnline ? "本地 Demo 已就绪" : "本地服务未连接"}</strong><small>内置 V7.3 结果 · 无 API 调用</small></div></div>
    </header>

    <section className="hero"><div><p className="eyebrow">LOCAL DEMO / A JSON</p><h1>把整集剧本，变成可执行的导演结构。</h1></div><p className="heroCopy">当前为纯本地演示模式。A 阶段、拼接提示词和逐镜模型评分全部读取已验收的内置数据，不连接 OpenRouter，不产生费用。</p></section>

    <form className="workbench" onSubmit={submit}>
      <div className="inputColumn">
        <section className="card promptCard">
          <div className="cardHead"><div><span>01</span><div><h2>导演 Prompt</h2><p>Demo 中仅用于展示，不会发送给外部模型</p></div></div><button type="button" className="textButton" onClick={() => promptInfo && setDirectorPrompt(promptInfo.prompt)} disabled={!promptInfo}>恢复默认</button></div>
          <textarea className="promptEditor" value={directorPrompt} onChange={(event) => setDirectorPrompt(event.target.value)} spellCheck={false} aria-label="导演 System Prompt" />
          <div className="editorMeta"><span>{directorPrompt.length.toLocaleString("zh-CN")} 字符</span><span>内部输出 · {promptInfo?.internal_output_format || "A1c"}</span><span>Reasoning · {promptInfo?.reasoning_effort || "provider default"}</span></div>
        </section>

        <section className="card">
          <div className="cardHead"><div><span>02</span><div><h2>项目参数</h2><p>导演层透传，不在这里选择视频模型</p></div></div><button type="button" className="textButton" onClick={() => void loadDemoInput()} disabled={!demoAvailable}>载入示例输入</button></div>
          <div className="fieldGrid">
            <label><span>集数 ID</span><input value={episodeId} onChange={(e) => setEpisodeId(e.target.value)} required /></label>
            <label><span>项目类型</span><input value={projectType} onChange={(e) => setProjectType(e.target.value)} required /></label>
            <label><span>画幅</span><select value={aspectRatio} onChange={(e) => setAspectRatio(e.target.value)}><option>9:16</option><option>16:9</option></select></label>
            <label><span>目标分辨率</span><select value={resolution} onChange={(e) => setResolution(e.target.value)}><option>720P</option><option>1080P</option></select></label>
            <label><span>路由档位</span><select value={tier} onChange={(e) => { setTier(e.target.value as RoutingTier); setCompiled(null); setDebugResult(null); }}><option value="low">LOW</option><option value="medium">MEDIUM</option><option value="high">HIGH</option></select></label>
            <div className="toggleField"><span>连续性跟踪</span><button type="button" role="switch" aria-label="连续性跟踪" aria-checked={continuityTracking} className={continuityTracking ? "toggle on" : "toggle"} onClick={() => setContinuityTracking((value) => !value)}><i /></button></div>
          </div>
          <label className="wideField"><span>全局视觉锁</span><input value={visualLock} onChange={(e) => setVisualLock(e.target.value)} placeholder="真人短剧、光影、色彩与质感" /></label>
          <label className="wideField"><span>用户反馈 <em>可选</em></span><input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="例如：节奏更紧、表演更克制" /></label>
        </section>

        <section className="card assetScriptCard">
          <div className="cardHead"><div><span>03</span><div><h2>资产与剧本</h2><p>资产只登记逻辑 ID，不需要 URL 或 file_id</p></div></div></div>
          <div className="sourceGrid">
            <label><span>注册资产 JSON</span><textarea value={assetsText} onChange={(e) => setAssetsText(e.target.value)} spellCheck={false} /></label>
            <label><span>上一集连续性 JSON <em>可选</em></span><textarea value={continuityText} onChange={(e) => setContinuityText(e.target.value)} spellCheck={false} /></label>
          </div>
          <label className="wideField scriptField"><span>整集剧本</span><textarea value={script} onChange={(e) => setScript(e.target.value)} placeholder="Demo 可直接加载，不需要先粘贴剧本……" /></label>
        </section>

        {(error || notice) && <div className={error ? "message error" : "message success"}>{error || notice}</div>}
        <button className="generateButton" type="submit" disabled={running || backendOnline !== true || !demoAvailable}><span>{running ? phase === "director" ? `正在加载内置 A 阶段 · ${elapsed}s` : `正在加载提示词与评分 · ${elapsed}s` : demoAvailable ? "加载 Demo A 阶段结果" : "内置 Demo 不可用"}</span><b>{running ? "•••" : "↗"}</b></button>
        <p className="securityNote">纯本地 Demo：不读取 API Key，不发送资产或剧本，不产生模型费用。</p>
      </div>

      <section className="card outputCard" aria-live="polite">
        <div className="cardHead outputHead"><div><span>04</span><div><h2>{compiled ? "拼接提示词与评分" : "A 阶段结果"}</h2><p>{result ? `${shots.length} 个原子分镜` : "等待导演输出"}</p></div></div>{result && <div className="outputActions"><button type="button" onClick={() => void copyResult()}>复制 A JSON</button><button type="button" onClick={() => saveFile(`${episodeId}_A导演输出.json`, jsonOutput)}>下载 A</button>{compiled?.final_video_plan && <button type="button" onClick={() => saveFile(`${episodeId}_${tier}_final_video_plan.json`, JSON.stringify(compiled.final_video_plan, null, 2))}>下载 Final</button>}</div>}</div>
        {!result && !running && <div className="emptyState"><div className="emptyIndex">A</div><h3>导演结构将在这里展开</h3><p>输出包括场景空间母版、原子分镜、镜头语言、比例锁、逻辑素材、能力需求、连续性与剪辑交接合同。</p></div>}
        {running && !result && <div className="emptyState runningState"><div className="orbit"><i /><span>A</span></div><h3>正在加载内置导演结构</h3><p>所有数据均来自本地已验收 Demo，不会请求外部模型。</p><div className="progressLine"><i /></div></div>}
        {result && <div className="resultBody">
          <div className="resultTabs"><button type="button" className={resultMode === "overview" ? "active" : ""} onClick={() => setResultMode("overview")}>{compiled ? "拼接提示词与评分" : "A 分镜概览"}</button><button type="button" className={resultMode === "json" ? "active" : ""} onClick={() => setResultMode("json")}>A 阶段 JSON</button></div>
          {!compiled && !running && <div className="nextStepPanel"><div><small>STEP 02</small><strong>Demo A 阶段已就绪</strong><p>直接读取内置 {tier.toUpperCase()} 档的完整 prompt_zh 和每镜候选模型评分。</p></div><button type="button" onClick={() => void compileNext()}>下一步：查看拼接提示词和评分 <b>→</b></button></div>}
          {running && phase === "routing" && <div className="routingBanner"><i /><span>导演分镜已完成，正在计算当前档位的模型候选评分…</span></div>}
          {resultMode === "overview" ? <><div className="metrics"><div><small>原子镜头</small><strong>{shots.length}</strong></div><div><small>场景上下文</small><strong>{result.director_plan.scene_contexts?.length || 0}</strong></div><div><small>预计总时长</small><strong>{totalDuration}s</strong></div><div><small>导演档位</small><strong>{result.director_plan.routing_tier?.toUpperCase() || tier.toUpperCase()}</strong></div></div>
            <div className="shotList">{shots.map((shot, index) => {
              const route = shot.atomic_id ? routingByAtomic.get(shot.atomic_id) : undefined;
              const decision = route?.routing_decision;
              const finalShot = route?.shot_id ? finalById.get(route.shot_id) : undefined;
              return <details key={shot.atomic_id || index} className="shotCard" open={index === 0}><summary><div><span>{String(index + 1).padStart(2, "0")}</span><strong>{shot.atomic_id || `shot-${index + 1}`}</strong></div><div className="shotBadges"><i>{shot.story_priority || "normal"}</i><i>{shot.narrative_class || "—"}</i>{decision?.selected_model && <i className="modelBadge">{decision.selected_display_name || decision.selected_model} · {decision.selected_preset}</i>}<b>{shot.atomic_duration || 0}s</b></div></summary><div className="shotDetail"><div className="shotFact"><small>叙事功能</small><p>{shot.narrative_function || "—"}</p></div><div className="shotFact"><small>场景资产</small><p>{shot.scene_asset || "—"}</p></div><div className="shotFact full"><small>本地时间轴</small><p>{shot.prompt_core?.timeline_local || "—"}</p></div><div className="shotFact full"><small>连续性</small><p>{shot.continuity ? `${shot.continuity.entry || "—"} → ${shot.continuity.exit || "—"}` : "—"}</p></div>
                {finalShot?.prompt_zh && <section className="compiledPrompt"><div><span>拼接完成的 prompt_zh</span><button type="button" onClick={() => void copyPrompt(finalShot.prompt_zh || "")}>复制提示词</button></div><pre>{finalShot.prompt_zh}</pre></section>}
                {decision ? <section className="routingPanel">
                  <div className="routingWinner"><div><small>最终选择</small><strong>{decision.selected_display_name || decision.selected_model}</strong><span>{decision.selected_preset}</span></div><div className="winnerMetrics"><span>质量 <b>{decision.fit_quality?.toFixed(2)}</b></span><span>可靠性 <b>{((decision.reliability || 0) * 100).toFixed(1)}%</b></span><span>预计可用积分 <b>{decision.expected_usable_points?.toFixed(2)}</b></span></div></div>
                  <p className="selectionReason">{selectedReason(decision)}</p>
                  <div className="scoreTableWrap"><table className="scoreTable"><thead><tr><th>模型 / Preset</th><th>准入</th><th>质量分</th><th>可靠性</th><th>调用积分</th><th>预计可用积分</th><th>档位分</th><th>结论</th></tr></thead><tbody>{(decision.candidates || []).map((candidate, candidateIndex) => <tr key={`${candidate.model}-${candidate.preset}-${candidateIndex}`} className={candidate.selected ? "selectedRow" : !candidate.qualified ? "invalidRow" : ""}><td><strong>{candidate.model}</strong><small>{candidate.preset}</small></td><td><span className={candidate.qualified ? "qualify yes" : "qualify no"}>{candidate.qualified ? "通过" : "淘汰"}</span></td><td><div className="scoreCell"><b>{candidate.fit_quality?.toFixed(2) || "—"}</b><i style={{ width: `${Math.max(0, Math.min(100, candidate.fit_quality || 0))}%` }} /></div></td><td>{candidate.reliability === undefined ? "—" : `${(candidate.reliability * 100).toFixed(1)}%`}</td><td>{candidate.call_points?.toFixed(2) || "—"}</td><td>{candidate.expected_usable_points?.toFixed(2) || "—"}</td><td>{candidate.tier_score?.toFixed(2) || "—"}</td><td className="reasonCell">{candidateReason(candidate)}</td></tr>)}</tbody></table></div>
                </section> : compiled ? <div className="routingPending">当前分镜没有匹配到路由结果</div> : null}
              </div></details>;
            })}</div></> : <pre className="jsonView">{jsonOutput}</pre>}
        </div>}
      </section>
    </form>

    {result && !compiled && !running && <button type="button" className="floatingNextButton" onClick={() => void compileNext()}><span>下一步</span><strong>查看拼接提示词和评分</strong><b>→</b></button>}

    <section className="card workflowCard">
      <div className="cardHead debugHead"><div><span>06</span><div><h2>生成执行工作流</h2><p>模型路由之后，四个环节可独立上传、生成、绑定或提交</p></div></div><div className="demoPill">LOCAL DEMO · 不产生费用</div></div>
      <div className="workflowStageBar">{WORKFLOW_STEPS.map((step) => <button type="button" key={step.id} className={workflowStep === step.id ? "active" : ""} onClick={() => { setWorkflowStep(step.id); resetWorkflowMessage(); }} disabled={!compiled}><i>{step.index}</i><span>{step.label}</span></button>)}</div>
      {!compiled && <div className="debugEmpty"><strong>请先完成“下一步：查看拼接提示词和评分”</strong><p>模型路由完成后，这里会读取每个 final shot 的视频提示词、逻辑资产与站位图计划。</p>{result && <button type="button" className="emptyNextButton" onClick={() => void compileNext()} disabled={running}>{running ? "正在加载…" : "直接进入下一步 →"}</button>}</div>}
      {compiled && <div className="workflowBody">
        {(workflowError || workflowNotice) && <div className={workflowError ? "message error" : "message success"}>{workflowError || workflowNotice}</div>}

        {workflowStep === "assets" && <>
          <div className="workflowIntro"><div><small>STEP 06 / ASSET REGISTRY</small><h3>上传并绑定图片资产</h3><p>每个逻辑资产 ID 可独立替换图片。上传后，后续站位图与视频任务会自动读取同一份登记表。</p></div><button type="button" onClick={() => void seedWorkflowAssets()} disabled={Boolean(workflowBusy)}>{workflowBusy === "seed" ? "正在登记…" : "载入内置 Demo 图片"}</button></div>
          <div className="workflowMetrics"><div><small>本计划图片资产</small><strong>{workflowAssets.length}</strong></div><div><small>已绑定</small><strong>{workflowAssets.filter((item) => assetRegistry[item.asset_id]).length}</strong></div><div><small>必需资产</small><strong>{workflowAssets.filter((item) => item.required).length}</strong></div><div><small>登记表总数</small><strong>{Object.keys(assetRegistry).length}</strong></div></div>
          <div className="assetRows">{workflowAssets.map((item) => {
            const binding = assetRegistry[item.asset_id];
            const uploading = workflowBusy === `upload:${item.asset_id}`;
            return <div className="assetRow" key={item.asset_id}><div className="assetIdentity"><span className={binding ? "assetState bound" : "assetState"}>{binding ? "已绑定" : "待上传"}</span><div><strong>{item.asset_id}</strong><small>{item.required ? "必需" : "可选"} · 被 {item.usedBy.length} 个分镜使用</small></div></div><div className="assetSource">{binding?.url ? <a href={`${API_BASE}${binding.url}`} target="_blank" rel="noreferrer">{binding.source === "user_upload" ? "用户图片" : binding.source === "bundled_demo_asset" ? "内置图片" : "查看图片"}</a> : <span>尚无文件</span>}<small>{binding?.original_filename ? decodeURIComponent(binding.original_filename) : "—"}</small></div><label className="uploadButton"><input type="file" accept="image/png,image/jpeg,image/webp" disabled={Boolean(workflowBusy)} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadWorkflowAsset(item.asset_id, file); event.currentTarget.value = ""; }} /><span>{uploading ? "上传中…" : binding ? "替换图片" : "上传图片"}</span></label></div>;
          })}</div>
        </>}

        {workflowStep === "references" && <>
          <div className="workflowIntro"><div><small>STEP 07 / POSITION REFERENCES</small><h3>用逐镜 JSON 提示词生成开始与结束站位图</h3><p>开始图使用该镜 JSON 提示词和角色/场景/道具原图生成；结束图再以开始图为编辑底图。两张图作为普通图片参考绑定。</p></div><div className="workflowActions"><button type="button" onClick={() => void generateReferenceShot()} disabled={Boolean(workflowBusy) || (imageGenerationMode === "provider" && !imageGenerationConfig?.configured)}>{workflowBusy === "reference-one" ? "正在生成两张图…" : imageGenerationMode === "provider" ? "调用图片模型生成当前分镜" : "登记当前 Demo 占位图"}</button><button type="button" className="secondary" onClick={() => void generateAllReferenceShots()} disabled={Boolean(workflowBusy) || imageGenerationMode === "provider"}>{workflowBusy === "reference-all" ? "正在批量生成…" : imageGenerationMode === "provider" ? "真实模式请逐镜生成" : "登记全部 Demo 占位图"}</button></div></div>
          <div className="generationModePanel"><div><span>图片来源模式</span><div><button type="button" className={imageGenerationMode === "demo" ? "active" : ""} onClick={() => setImageGenerationMode("demo")}>Demo 占位图</button><button type="button" className={imageGenerationMode === "provider" ? "active real" : ""} onClick={() => setImageGenerationMode("provider")}>真实图片模型</button></div></div><label><span>图片模型</span><input value={imageModel} onChange={(event) => setImageModel(event.target.value)} disabled={imageGenerationMode !== "provider"} /></label><aside><small>提示词来源</small><strong>final_video_plan.shots[当前镜].reference_image_plan</strong><p>{imageGenerationMode === "provider" ? imageGenerationConfig?.configured ? `将调用 OpenRouter Images API · ${imageGenerationConfig.resolution} · ${imageGenerationConfig.quality}，会产生两张图片的费用。` : "后端没有配置 OPENROUTER_API_KEY，真实生成按钮不可用。" : "只验证流程，不调用图片模型；显示的图片不是该分镜真实生成结果。"}</p></aside></div>
          <label className="shotSelector"><span>选择分镜片段</span><select value={selectedWorkflowShot?.shot_id || ""} onChange={(event) => setSelectedWorkflowShotId(event.target.value)}>{finalShots.map((shot) => <option key={shot.shot_id} value={shot.shot_id}>{shot.shot_id} · {shot.model} · {shot.duration}s</option>)}</select></label>
          {selectedWorkflowShot && <div className="referenceWorkspace">
            <div className="promptPair"><section><div><span>开始站位图提示词</span><small>{selectedWorkflowShot.reference_image_plan?.output_asset_ids?.entry}</small></div><pre>{selectedWorkflowShot.reference_image_plan?.entry_state_reference_prompt_zh || "该分镜没有开始图提示词"}</pre></section><section><div><span>结束站位图编辑提示词</span><small>{selectedWorkflowShot.reference_image_plan?.output_asset_ids?.exit}</small></div><pre>{selectedWorkflowShot.reference_image_plan?.exit_state_reference_edit_prompt_zh || "该分镜没有结束图提示词"}</pre></section></div>
            <div className="referenceInputAssets"><span>自动使用的图片资产</span><div>{(selectedWorkflowShot.reference_image_plan?.input_asset_ids || []).map((assetId) => <i key={assetId} className={assetRegistry[assetId] ? "ready" : ""}>{assetRegistry[assetId] ? "✓" : "!"} {assetId}</i>)}</div></div>
            {selectedReferenceManifest ? <div className="referenceImages"><figure><div>{selectedReferenceManifest.entry?.image_url && <img src={`${API_BASE}${selectedReferenceManifest.entry.image_url}`} alt={`${selectedWorkflowShot.shot_id} 开始站位图`} />}</div><figcaption><strong>开始站位图</strong><small>{selectedReferenceManifest.entry?.asset_id}</small></figcaption></figure><figure><div>{selectedReferenceManifest.exit?.image_url && <img src={`${API_BASE}${selectedReferenceManifest.exit.image_url}`} alt={`${selectedWorkflowShot.shot_id} 结束站位图`} />}</div><figcaption><strong>结束站位图</strong><small>{selectedReferenceManifest.exit?.asset_id}</small></figcaption></figure><aside><span>生成状态</span><strong>{selectedReferenceManifest.status}</strong><p>{selectedReferenceManifest.message}</p>{selectedReferenceManifest.image_model && <em>{selectedReferenceManifest.image_model}</em>}{selectedReferenceManifest.demo_placeholder && <b>当前为流程占位样图，不是逐镜真实生成</b>}</aside></div> : <div className="referenceEmpty">当前分镜尚未生成站位图。先确认上方所用资产均为 ✓，然后选择“真实图片模型”生成。</div>}
          </div>}
          {referenceBulk && <div className="workflowJsonSummary"><div><span>批量结果</span><b>完成 {referenceBulk.completed_count || 0} · 阻塞 {referenceBulk.blocked_count || 0}</b></div><pre>{JSON.stringify(referenceBulk.blocked || [], null, 2)}</pre></div>}
        </>}

        {workflowStep === "binding" && <>
          <div className="workflowIntro"><div><small>STEP 08 / AUTO BINDING</small><h3>自动绑定视频提示词、站位图与逻辑资产</h3><p>此步骤不生成内容，只检查每个分镜所需资产，并形成可直接交给视频提供商适配器的 payload。</p></div><button type="button" onClick={() => void runAutoBinding()} disabled={Boolean(workflowBusy)}>{workflowBusy === "binding" ? "正在检查…" : "运行独立绑定检查"}</button></div>
          {bindingResult ? <><div className="workflowMetrics"><div><small>可提交分镜</small><strong>{bindingResult.ready_count || 0}</strong></div><div><small>阻塞分镜</small><strong>{bindingResult.blocked_count || 0}</strong></div><div><small>登记资产</small><strong>{bindingResult.registry_count || 0}</strong></div><div><small>计划分镜</small><strong>{finalShots.length}</strong></div></div><div className="bindingGrid"><section><h4>阻塞详情</h4><pre>{JSON.stringify(bindingResult.blocked || [], null, 2)}</pre></section><section><h4>首个就绪 Payload</h4><pre>{JSON.stringify(bindingResult.ready?.[0] || {}, null, 2)}</pre></section></div></> : <div className="debugEmpty compact"><strong>尚未运行绑定检查</strong><p>它会明确区分“原始图片资产缺失”和“开始/结束站位图尚未生成”。</p></div>}
        </>}

        {workflowStep === "submit" && <>
          <div className="workflowIntro"><div><small>STEP 09 / VIDEO QUEUE</small><h3>送往视频生成流程</h3><p>系统会先自动绑定每个镜头的视频提示词、开始图、结束图和所用资产；只有完整分镜才进入队列。</p></div><button type="button" onClick={() => void submitVideoJobs()} disabled={Boolean(workflowBusy)}>{workflowBusy === "submit" ? "正在提交…" : "提交完整分镜到视频队列"}</button></div>
          <div className="localWarning"><b>Demo 提交模式</b><span>当前只在本地创建 queued_demo 任务清单，不会调用真实视频模型或扣费。</span></div>
          {submitResult ? <><div className="workflowMetrics"><div><small>已入队</small><strong>{submitResult.submitted_count || 0}</strong></div><div><small>被阻塞</small><strong>{submitResult.blocked_count || 0}</strong></div><div><small>登记资产</small><strong>{submitResult.registry_count || 0}</strong></div><div><small>执行模式</small><strong className="smallValue">LOCAL</strong></div></div><div className="jobRows">{(submitResult.jobs || []).slice(0, 12).map((job) => <div key={job.job_id}><span>{job.shot_id}</span><strong>{job.status}</strong><small>{job.bound_asset_ids?.length || 0} 个图片绑定 · 含 {job.derived_reference_ids?.length || 0} 张站位图</small><code>{job.job_id}</code></div>)}</div>{(submitResult.jobs?.length || 0) > 12 && <p className="jobMore">另有 {(submitResult.jobs?.length || 0) - 12} 个任务已入队。</p>}<div className="workflowJsonSummary"><div><span>未提交分镜</span><b>{submitResult.blocked_count || 0}</b></div><pre>{JSON.stringify(submitResult.blocked || [], null, 2)}</pre></div></> : <div className="debugEmpty compact"><strong>等待独立提交</strong><p>提交动作会实时重新检查绑定，因此不要求必须先手动点击上一步。</p></div>}
        </>}
      </div>}
    </section>

    <section className="card debugCard">
      <div className="cardHead debugHead"><div><span>05</span><div><h2>流水线环节调试器</h2><p>任选一个环节独立查看，不需要从 A 阶段重新开始</p></div></div><div className="debugTier">当前档位 <b>{tier.toUpperCase()}</b></div></div>
      <div className="debugStageBar">{DEBUG_STAGES.map((stage) => <button type="button" key={stage.id} className={debugStage === stage.id ? "active" : ""} onClick={() => void loadDebugStage(stage.id)} disabled={debugLoading}><i>{stage.index}</i><span>{stage.label}</span></button>)}</div>
      {!debugStage && <div className="debugEmpty"><strong>选择一个环节开始调试</strong><p>每个环节都会显示输入制品、输出摘要、JSON 预览和完整制品下载。</p></div>}
      {debugLoading && <div className="debugEmpty"><strong>正在读取该环节的本地制品…</strong></div>}
      {debugError && <div className="message error debugMessage">{debugError}</div>}
      {debugResult && !debugLoading && <div className="debugBody">
        <div className="debugIntro"><div><small>{debugResult.stage.toUpperCase()} / {debugResult.tier.toUpperCase()}</small><h3>{debugResult.title}</h3><p>{debugResult.description}</p></div><a href={`${API_BASE}${debugResult.download_url}`} download>下载完整制品 <b>↓</b></a></div>
        <div className="debugFlow"><div><small>INPUT</small><strong>{debugResult.input_artifact}</strong></div><b>→</b><div><small>OUTPUT</small><strong>{debugResult.output_artifact}</strong><span>{(debugResult.output_size_bytes / 1024).toFixed(1)} KB</span></div></div>
        <div className="debugMetrics">{Object.entries(debugResult.summary).map(([key, value]) => <div key={key}><small>{key}</small><strong>{String(value ?? "—")}</strong></div>)}</div>
        <div className="debugJsonHead"><span>JSON 调试预览</span><small>大数组仅展示前 3 项，完整数据请下载制品</small></div>
        <pre className="debugJson">{JSON.stringify(debugResult.preview, null, 2)}</pre>
      </div>}
    </section>
  </main>;
}
