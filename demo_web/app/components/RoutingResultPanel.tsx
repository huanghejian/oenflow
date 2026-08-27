import ReferenceFrameSlots from "./ReferenceFrameSlots";
import type { FinalShot, ReferenceManifest, RoutingShot, ShotGroup } from "./autoflowTypes";

type RoutingResultPanelProps = {
  routingShots: RoutingShot[];
  finalShots: FinalShot[];
  references: Record<string, ReferenceManifest>;
  apiBase: string;
  pendingGroups?: ShotGroup[];
  isGenerating?: boolean;
};

function pct(value?: number): string {
  return value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function score(value?: number): string {
  return value === undefined ? "—" : String(value);
}

const DIFFICULTY_LABELS: Record<string, string> = {
  low: "低难度",
  medium: "中等难度",
  high: "高难度",
  critical: "关键高难",
};

const REQUIREMENT_LABELS: Record<string, string> = {
  acting_precision: "表演",
  dialogue_lipsync: "口型",
  identity_consistency: "身份一致",
  multi_character_control: "多人控制",
  motion_action: "动作",
  physical_interaction: "物理互动",
  camera_control: "运镜",
  prop_precision: "道具",
  vfx_environment: "特效环境",
  temporal_continuity: "时序连续",
};

export default function RoutingResultPanel({ routingShots, finalShots, references, apiBase, pendingGroups = [], isGenerating = false }: RoutingResultPanelProps) {
  if (!routingShots.length && !finalShots.length) {
    if (!pendingGroups.length) return <div className="autoEmpty">尚未执行路由与首尾帧生成。</div>;
    return (
      <section className="pendingFrameWorkspace">
        <header className={isGenerating ? "is-generating" : ""}>
          <i />
          <div>
            <strong>{isGenerating ? "首尾站位图正在并行生成" : "首尾站位图槽位已就绪"}</strong>
            <span>{pendingGroups.length} 个镜头组 · {pendingGroups.length * 2} 张竖屏线稿</span>
          </div>
        </header>
        <div className="pendingFrameGrid">
          {pendingGroups.map((group) => (
            <article key={group.group_id}>
              <header><strong>{group.group_id}</strong><span>{group.duration || 0}s</span></header>
              <ReferenceFrameSlots shotId={group.group_id} apiBase={apiBase} isGenerating={isGenerating} compact />
            </article>
          ))}
        </div>
      </section>
    );
  }

  const finalById = new Map(finalShots.map((shot) => [shot.shot_id, shot]));

  return (
    <>
      {isGenerating ? (
        <div className="referenceGenerationLive">
          <i /><div><strong>正在重新路由并生成首尾站位图</strong><span>旧结果暂时保留；同步请求返回后，各槽位会显示新图片或失败原因。</span></div>
        </div>
      ) : null}
      <div className="routingResultGrid">
      {routingShots.map((route) => {
        const decision = route.routing_decision;
        const difficulty = route.difficulty_analysis;
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
            <div className={`difficultySummary difficulty-${difficulty?.overall_difficulty || "unknown"}`}>
              <header>
                <span>镜头组汇总难度</span>
                <b>{difficulty?.difficulty_score === undefined ? "等待分析" : `${difficulty.difficulty_score} 分 · ${DIFFICULTY_LABELS[difficulty?.overall_difficulty || ""] || "未分级"}`}</b>
              </header>
              <p>{difficulty?.reason || "尚未返回镜头难度分析。"}</p>
              {difficulty?.risks?.length ? (
                <div>{difficulty.risks.map((risk, index) => <span key={`${risk}-${index}`}>{risk}</span>)}</div>
              ) : null}
              <section className="difficultyDimensions">
                {Object.entries(route.routing_requirements || {}).map(([key, level]) => (
                  <span key={key} className={`level-${level}`}>
                    <small>{REQUIREMENT_LABELS[key] || key}</small>
                    <b>{DIFFICULTY_LABELS[level] || level}</b>
                  </span>
                ))}
              </section>
            </div>
            <div className="subShotScorePanel">
              <header>
                <strong>逐个小镜头难度打分</strong>
                <span>{difficulty?.sub_shot_scores?.length || 0} 个镜头</span>
              </header>
              {difficulty?.sub_shot_scores?.length ? (
                <div className="subShotScoreTableWrap">
                  <table className="subShotScoreTable">
                    <thead>
                      <tr>
                        <th>镜头</th>
                        <th>总分</th>
                        {Object.entries(REQUIREMENT_LABELS).map(([key, label]) => <th key={key}>{label}</th>)}
                        <th>判断原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {difficulty.sub_shot_scores.map((item) => (
                        <tr key={item.sub_shot_id}>
                          <td><strong>{item.sub_shot_id || "—"}</strong><small>{DIFFICULTY_LABELS[item.overall_difficulty || ""] || "未分级"}</small></td>
                          <td><b className={`difficultyScore difficultyScore-${item.overall_difficulty || "unknown"}`}>{score(item.difficulty_score)}</b></td>
                          {Object.keys(REQUIREMENT_LABELS).map((key) => <td key={key}>{score(item.dimension_scores?.[key])}</td>)}
                          <td><p>{item.reason || "—"}</p>{item.risks?.length ? <small>{item.risks.join("；")}</small> : null}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="subShotScoreEmpty">尚未返回逐镜头分数，请重新执行路由与首尾帧。</p>}
            </div>
            <div className="selectionReason">
              <small>为什么选择这个模型</small>
              <p>{decision?.selection_reason || "等待路由器生成选择理由。"}</p>
            </div>
            <div className="modelScoreTable">
              <table>
                <thead>
                  <tr>
                    <th>视频模型</th>
                    <th>状态</th>
                    <th>Preset</th>
                    <th>适配分</th>
                    <th>可靠性</th>
                    <th>预计积分</th>
                    <th>判断理由</th>
                  </tr>
                </thead>
                <tbody>
                  {(decision?.model_comparison || []).map((candidate) => (
                    <tr
                      key={candidate.model}
                      className={candidate.selected ? "selected" : candidate.qualified ? "qualified" : "rejected"}
                    >
                      <td><strong>{candidate.display_name || candidate.model}</strong></td>
                      <td>{candidate.selected ? "已选择" : candidate.qualified ? "可用" : "淘汰"}</td>
                      <td>{candidate.preset || "—"}</td>
                      <td>{candidate.fit_quality?.toFixed(2) || "—"}</td>
                      <td>{pct(candidate.reliability)}</td>
                      <td>{candidate.expected_usable_points?.toFixed(2) || "—"}</td>
                      <td>{candidate.why || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="routePrompt">
              <small>分镜提示词</small>
              <pre>{finalShot?.prompt_zh || "暂无提示词"}</pre>
            </div>
            <div className="referenceGenerationMeta">
              <strong>镜头组站位参考图</strong>
              <span>
                {manifest?.provider === "volcengine_ark" ? "星图 5.0 Pro" : manifest?.provider || (manifest?.demo_placeholder ? "Demo 占位" : "等待生成")}
                {manifest?.size ? ` · ${manifest.size}` : ""}
                {` · ${manifest?.aspect_ratio || "9:16"}`}
              </span>
            </div>
            <ReferenceFrameSlots
              shotId={route.shot_id}
              manifest={manifest}
              plan={finalShot?.reference_image_plan}
              apiBase={apiBase}
              isGenerating={isGenerating}
            />
          </article>
        );
      })}
      </div>
    </>
  );
}
