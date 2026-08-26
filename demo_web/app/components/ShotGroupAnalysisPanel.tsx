import type { ShotGroup } from "./autoflowTypes";

type ShotGroupAnalysisPanelProps = {
  groups: ShotGroup[];
};

const GROUP_LABELS: Record<string, string> = {
  continuous_take: "连续拍摄",
  min_duration_pack: "4秒拼接",
  independent: "独立镜头组",
};

export default function ShotGroupAnalysisPanel({ groups }: ShotGroupAnalysisPanelProps) {
  if (!groups.length) {
    return <div className="autoEmpty">尚未分析镜头组。</div>;
  }

  return (
    <div className="shotGroupPanel">
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
          </div>
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
