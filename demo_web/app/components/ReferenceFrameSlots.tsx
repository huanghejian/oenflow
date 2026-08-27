"use client";

import { useState } from "react";
import type { FinalShot, ReferenceManifest } from "./autoflowTypes";

type ReferenceFrameSlotsProps = {
  shotId?: string;
  manifest?: ReferenceManifest;
  plan?: FinalShot["reference_image_plan"];
  apiBase: string;
  isGenerating?: boolean;
  generatingRole?: FrameRole;
  onGenerate?: (role: FrameRole) => void;
  generationEnabled?: boolean;
  compact?: boolean;
  uploadProgress?: Partial<Record<FrameRole, number>>;
  onUploadFrame?: (role: FrameRole) => void;
  uploadDisabled?: boolean;
};

type FrameRole = "entry" | "exit";

const ASSET_TYPE_LABELS: Record<string, string> = {
  scene: "场景",
  role: "角色",
  character: "角色",
  prop: "道具",
  item: "道具",
};

function imageSource(apiBase: string, imageUrl: string): string {
  return /^https?:\/\//i.test(imageUrl) ? imageUrl : `${apiBase}${imageUrl}`;
}

function isRemoteImage(imageUrl?: string): boolean {
  return /^https?:\/\//i.test(imageUrl || "");
}

function frameState(
  role: FrameRole,
  manifest: ReferenceManifest | undefined,
  isGenerating: boolean,
  uploadPercent?: number,
): { key: string; label: string; hint: string } {
  const frame = manifest?.[role];
  if (uploadPercent !== undefined) {
    return { key: "uploading", label: `上传 ${uploadPercent}%`, hint: "正在上传到前端 R2" };
  }
  if (isGenerating) {
    return frame?.image_url
      ? { key: "generating", label: "重新生成中", hint: "旧图保留，正在等待新图返回" }
      : { key: "generating", label: "正在生成", hint: "星图同步请求处理中" };
  }
  if (frame?.image_url) {
    return isRemoteImage(frame.image_url)
      ? { key: "uploaded", label: "已上传", hint: "前端 R2 图片已绑定到当前镜头" }
      : { key: "completed", label: "已生成", hint: "正在等待浏览器上传前端 R2" };
  }
  if (["blocked", "failed", "error"].includes(String(manifest?.status || "").toLowerCase())) {
    return { key: "failed", label: "生成失败", hint: "请查看本步骤的阻塞原因后重试" };
  }
  return { key: "waiting", label: "等待生成", hint: "融合本镜头所需的角色、场景和道具图片" };
}

export default function ReferenceFrameSlots({
  shotId,
  manifest,
  plan,
  apiBase,
  isGenerating = false,
  generatingRole,
  onGenerate,
  generationEnabled = false,
  compact = false,
  uploadProgress,
}: ReferenceFrameSlotsProps) {
  const [preview, setPreview] = useState<{ src: string; title: string } | null>(null);
  return (
    <>
      {manifest?.input_asset_bindings?.length ? (
        <section className="referenceBindingPanel">
          <header>
            <strong>融合图片来源</strong>
            <span>{manifest.input_asset_bindings.filter((item) => item.binding_status === "bound").length}/{manifest.input_asset_bindings.length} 已绑定</span>
          </header>
          <div className="referenceBindingList">
            {manifest.input_asset_bindings.map((binding) => (
              <figure className={binding.binding_status === "bound" ? "bound" : "missing"} key={binding.asset_id}>
                <div>
                  {binding.url ? <img src={imageSource(apiBase, binding.url)} alt={binding.asset_id || "输入图片"} /> : <span>缺图</span>}
                </div>
                <figcaption>
                  <b>{ASSET_TYPE_LABELS[binding.asset_type || ""] || "资产"}</b>
                  <small>{binding.asset_id || "未知资产"}</small>
                </figcaption>
              </figure>
            ))}
          </div>
          {manifest.missing_asset_ids?.length ? <p>缺少：{manifest.missing_asset_ids.join("、")}，请先补齐图片。</p> : null}
        </section>
      ) : null}
      <div className={`routeRefs frameSlots${compact ? " compact" : ""}`}>
        {(["entry", "exit"] as const).map((role) => {
          const frame = manifest?.[role];
          const roleGenerating = isGenerating || generatingRole === role;
          const state = frameState(role, manifest, roleGenerating, uploadProgress?.[role]);
          const title = role === "entry" ? "开始融合图" : "结束融合图";
          const fallbackId = role === "entry" ? plan?.output_asset_ids?.entry : plan?.output_asset_ids?.exit;
          const canGenerateRole = generationEnabled && !roleGenerating;
          return (
            <figure className={`frameSlot state-${state.key}`} key={role}>
              <div className="frameSlotCanvas">
                {frame?.image_url ? (
                  <button
                    type="button"
                    className="frameImageButton"
                    onClick={() => setPreview({ src: imageSource(apiBase, frame.image_url || ""), title: `${shotId || "镜头"} ${title}` })}
                    aria-label={`放大查看${shotId || "镜头"}${title}`}
                  >
                    <img src={imageSource(apiBase, frame.image_url)} alt={`${shotId || "镜头"} ${title}`} />
                    <span>点击查看原图</span>
                  </button>
                ) : (
                  <div className="frameSlotPlaceholder">
                    <i aria-hidden="true"><span /></i>
                    <strong>{state.label}</strong>
                    <small>{state.hint}</small>
                  </div>
                )}
                <em className="frameSlotStatus"><i />{state.label}</em>
              </div>
              <figcaption>
                <div>
                  <strong>{title}</strong>
                  <small>{frame?.storage?.status === "uploaded" ? "已上传前端 R2" : frame?.asset_id || fallbackId || `${shotId || "shot"}_${role}`}</small>
                </div>
                {onGenerate ? (
                  <button type="button" className="frameGenerateButton" onClick={() => onGenerate(role)} disabled={!canGenerateRole}>
                    {roleGenerating ? "生成并上传中..." : frame?.image_url ? "重新生成" : role === "entry" ? "生成开始图" : "生成结束图"}
                  </button>
                ) : null}
              </figcaption>
            </figure>
          );
        })}
      </div>
      {preview ? (
        <div className="framePreviewModalBackdrop" role="presentation" onClick={() => setPreview(null)}>
          <section className="framePreviewModal" role="dialog" aria-modal="true" aria-label={preview.title} onClick={(event) => event.stopPropagation()}>
            <header>
              <strong>{preview.title}</strong>
              <button type="button" onClick={() => setPreview(null)}>关闭</button>
            </header>
            <div><img src={preview.src} alt={preview.title} /></div>
          </section>
        </div>
      ) : null}
    </>
  );
}
