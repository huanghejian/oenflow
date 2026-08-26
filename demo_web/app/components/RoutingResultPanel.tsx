import type { FinalShot, ReferenceManifest, RoutingShot } from "./autoflowTypes";

type RoutingResultPanelProps = {
  routingShots: RoutingShot[];
  finalShots: FinalShot[];
  references: Record<string, ReferenceManifest>;
  apiBase: string;
};

function pct(value?: number): string {
  return value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

export default function RoutingResultPanel({ routingShots, finalShots, references, apiBase }: RoutingResultPanelProps) {
  if (!routingShots.length && !finalShots.length) {
    return <div className="autoEmpty">尚未执行路由与首尾帧生成。</div>;
  }

  const finalById = new Map(finalShots.map((shot) => [shot.shot_id, shot]));

  return (
    <div className="routingResultGrid">
      {routingShots.map((route) => {
        const decision = route.routing_decision;
        const finalShot = finalById.get(route.shot_id);
        const manifest = route.shot_id ? references[route.shot_id] : undefined;
        return (
          <article className="routeCard" key={route.shot_id || route.source_group}>
            <header>
              <div>
                <small>{route.source_group || route.shot_id}</small>
                <strong>{decision?.selected_display_name || decision?.selected_model || "未选择模型"}</strong>
                <span>{decision?.selected_preset || "—"}</span>
              </div>
              <b>{route.duration || finalShot?.duration || 0}s</b>
            </header>
            <div className="routeMetrics">
              <span>质量 <b>{decision?.fit_quality?.toFixed(2) || "—"}</b></span>
              <span>可靠性 <b>{pct(decision?.reliability)}</b></span>
              <span>预计积分 <b>{decision?.expected_usable_points?.toFixed(2) || "—"}</b></span>
            </div>
            <div className="candidateStrip">
              {(decision?.candidates || []).slice(0, 8).map((candidate, index) => (
                <span key={`${candidate.model}-${candidate.preset}-${index}`} className={candidate.selected ? "selected" : candidate.qualified ? "" : "rejected"}>
                  {candidate.model} / {candidate.preset}
                  <b>{candidate.qualified ? candidate.fit_quality?.toFixed(1) : "淘汰"}</b>
                </span>
              ))}
            </div>
            <div className="routePrompt">
              <small>分镜提示词</small>
              <pre>{finalShot?.prompt_zh || "暂无提示词"}</pre>
            </div>
            <div className="routeRefs">
              <figure>
                <div>{manifest?.entry?.image_url ? <img src={`${apiBase}${manifest.entry.image_url}`} alt={`${route.shot_id} 首帧`} /> : <span>首帧未生成</span>}</div>
                <figcaption>{manifest?.entry?.asset_id || finalShot?.reference_image_plan?.output_asset_ids?.entry || "entry"}</figcaption>
              </figure>
              <figure>
                <div>{manifest?.exit?.image_url ? <img src={`${apiBase}${manifest.exit.image_url}`} alt={`${route.shot_id} 尾帧`} /> : <span>尾帧未生成</span>}</div>
                <figcaption>{manifest?.exit?.asset_id || finalShot?.reference_image_plan?.output_asset_ids?.exit || "exit"}</figcaption>
              </figure>
            </div>
          </article>
        );
      })}
    </div>
  );
}
