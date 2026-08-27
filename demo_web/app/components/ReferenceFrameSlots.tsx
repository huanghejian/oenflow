import type { FinalShot, ReferenceManifest } from "./autoflowTypes";

type ReferenceFrameSlotsProps = {
  shotId?: string;
  manifest?: ReferenceManifest;
  plan?: FinalShot["reference_image_plan"];
  apiBase: string;
  isGenerating?: boolean;
  compact?: boolean;
};

type FrameRole = "entry" | "exit";

function imageSource(apiBase: string, imageUrl: string): string {
  return /^https?:\/\//i.test(imageUrl) ? imageUrl : `${apiBase}${imageUrl}`;
}

function frameState(
  role: FrameRole,
  manifest: ReferenceManifest | undefined,
  isGenerating: boolean,
): { key: string; label: string; hint: string } {
  const frame = manifest?.[role];
  if (isGenerating) {
    return frame?.image_url
      ? { key: "generating", label: "重新生成中", hint: "旧图保留，正在等待新图返回" }
      : { key: "generating", label: "正在生成", hint: "星图同步请求处理中" };
  }
  if (frame?.image_url) return { key: "completed", label: "已生成", hint: "图片已绑定到当前镜头" };
  if (["blocked", "failed", "error"].includes(String(manifest?.status || "").toLowerCase())) {
    return { key: "failed", label: "生成失败", hint: "请查看本步骤的阻塞原因后重试" };
  }
  return { key: "waiting", label: "等待生成", hint: "执行路由后将生成此站位图" };
}

export default function ReferenceFrameSlots({
  shotId,
  manifest,
  plan,
  apiBase,
  isGenerating = false,
  compact = false,
}: ReferenceFrameSlotsProps) {
  return (
    <div className={`routeRefs frameSlots${compact ? " compact" : ""}`}>
      {(["entry", "exit"] as const).map((role) => {
        const frame = manifest?.[role];
        const state = frameState(role, manifest, isGenerating);
        const title = role === "entry" ? "开始站位图" : "结束站位图";
        const fallbackId = role === "entry" ? plan?.output_asset_ids?.entry : plan?.output_asset_ids?.exit;
        return (
          <figure className={`frameSlot state-${state.key}`} key={role}>
            <div className="frameSlotCanvas">
              {frame?.image_url ? (
                <img src={imageSource(apiBase, frame.image_url)} alt={`${shotId || "镜头"} ${title}`} />
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
              <strong>{title}</strong>
              <small>{frame?.asset_id || fallbackId || `${shotId || "shot"}_${role}`}</small>
            </figcaption>
          </figure>
        );
      })}
    </div>
  );
}
