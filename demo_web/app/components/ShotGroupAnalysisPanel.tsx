import type { Dialogue, ShotGroup } from "./autoflowTypes";

type ShotGroupAnalysisPanelProps = {
  groups: ShotGroup[];
};

const GROUP_LABELS: Record<string, string> = {
  continuous_take: "连续表演镜头组",
  min_duration_pack: "不足 4 秒相邻合并组",
  independent: "独立表演单元",
};

function dialogueText(dialogue?: Dialogue): string {
  if (!dialogue || typeof dialogue !== "object") return "";
  const value = dialogue as { speaker?: string; content?: string; source_content?: string };
  const content = value.content || value.source_content || "";
  return content ? `${value.speaker ? `${value.speaker}：` : ""}${content}` : "";
}

export default function ShotGroupAnalysisPanel({ groups }: ShotGroupAnalysisPanelProps) {
  if (!groups.length) {
    return <div className="autoEmpty">尚未分析镜头组。</div>;
  }

  const subShotCount = groups.reduce((total, group) => total + (group.sub_shots?.length || group.sub_shot_ids.length), 0);
  const continuousCount = groups.filter((group) => group.group_type === "continuous_take").length;

  return (
    <div className="shotGroupPanel">
      <section className="shotGroupOverview">
        <div><b>{groups.length}</b><span>镜头组</span></div>
        <div><b>{subShotCount}</b><span>组内子镜头</span></div>
        <div><b>{continuousCount}</b><span>连续镜头组</span></div>
        <div><b>{groups.length - continuousCount}</b><span>独立镜头组</span></div>
      </section>
      {groups.map((group) => (
        <article className="shotGroupCard" key={group.group_id}>
          <header>
            <div>
              <span>{GROUP_LABELS[group.group_type] || group.group_type}</span>
              <strong>{group.group_id}</strong>
            </div>
            <b>{group.duration}s</b>
          </header>
          <p>{group.reason}</p>
          <div className="groupMeta">
            <span>分镜：{group.source_segment_ids.join("、") || "—"}</span>
            <span>子镜头：{group.sub_shot_ids.join("、") || "—"}</span>
            <span className={group.duration >= 4 ? "durationReady" : "durationPadding"}>
              {group.duration >= 4 ? "已达到 4 秒生成时长" : `不足 4 秒，必须再合并 ${Math.max(0, 4 - group.duration)} 秒`}
            </span>
          </div>
          <section className="groupSubShots">
            <div className="groupSubShotsTitle">
              <strong>镜头组内容</strong>
              <span>{group.sub_shots?.length || group.sub_shot_ids.length} 个子镜头 · 按拍摄顺序排列</span>
            </div>
            <div className="groupSubShotList">
              {(group.sub_shots || []).map((shot, shotIndex) => {
                const dialogue = dialogueText(shot.dialogue);
                return (
                  <article className="groupSubShot" key={shot.id || `${group.group_id}-${shotIndex}`}>
                    <div className="groupSubShotTop">
                      <span>{String(shotIndex + 1).padStart(2, "0")}</span>
                      <strong>{shot.id || `子镜头 ${shotIndex + 1}`}</strong>
                      <b>{shot.duration}s</b>
                    </div>
                    <p>{shot.content || shot.performance || "暂无子镜头内容"}</p>
                    <div className="groupSubShotFacts">
                      {shot.scene ? <span>场景 · {shot.scene}</span> : null}
                      {shot.shot_type ? <span>景别 · {shot.shot_type}</span> : null}
                      {shot.camera_movement ? <span>运镜 · {shot.camera_movement}</span> : null}
                      {shot.characters?.length ? <span>人物 · {shot.characters.join("、")}</span> : null}
                    </div>
                    {shot.performance && shot.performance !== shot.content ? (
                      <div className="groupSubShotDetail"><small>表演动作</small><span>{shot.performance}</span></div>
                    ) : null}
                    {dialogue ? <div className="groupSubShotDetail"><small>台词</small><span>{dialogue}</span></div> : null}
                    {(shot.entry_state || shot.exit_state) ? (
                      <div className="groupSubShotStates">
                        <span><small>进入状态</small>{shot.entry_state || "—"}</span>
                        <i>→</i>
                        <span><small>结束状态</small>{shot.exit_state || "—"}</span>
                      </div>
                    ) : null}
                  </article>
                );
              })}
              {!group.sub_shots?.length ? (
                <div className="groupSubShotsMissing">当前旧结果只包含子镜头编号，请重新执行镜头组分析以显示完整内容。</div>
              ) : null}
            </div>
          </section>
          <div className="groupPrompts">
            <section>
              <small>镜头组首帧提示词</small>
              <pre>{group.entry_prompt_zh}</pre>
            </section>
            <section>
              <small>镜头组尾帧提示词</small>
              <pre>{group.exit_prompt_zh}</pre>
            </section>
          </div>
        </article>
      ))}
    </div>
  );
}
