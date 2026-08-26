import type { Segment } from "./autoflowTypes";

type StoryboardAccordionProps = {
  segments: Segment[];
};

function joinList(values?: string[]): string {
  return values?.filter(Boolean).join("、") || "—";
}

export default function StoryboardAccordion({ segments }: StoryboardAccordionProps) {
  if (!segments.length) {
    return <div className="autoEmpty">暂无分镜，请先完成第一步拆镜。</div>;
  }

  return (
    <div className="storyboardAccordion">
      {segments.map((segment, index) => (
        <details key={segment.segment_id || index} open={index === 0}>
          <summary>
            <div>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{segment.segment_id}</strong>
              <small>{segment.scene || "未命名场景"}</small>
            </div>
            <b>{segment.duration || 0}s</b>
          </summary>
          <div className="segmentBody">
            <div className="segmentFacts">
              <span>景别：{segment.shot_type || "—"}</span>
              <span>运镜：{segment.camera_movement || "—"}</span>
              <span>角色：{joinList(segment.characters)}</span>
              <span>物品：{joinList(segment.items)}</span>
            </div>
            <p>{segment.performance || segment.frame_background || "暂无分镜描述"}</p>
            <div className="subShotGrid">
              {(segment.sub_shots || []).map((subShot) => (
                <details key={subShot.id} className="subShotCard">
                  <summary>
                    <span>{subShot.id}</span>
                    <strong>{subShot.duration || 0}s</strong>
                    <small>{subShot.shot_type || "子镜头"}</small>
                  </summary>
                  <div>
                    <dl>
                      <dt>入场</dt>
                      <dd>{subShot.entry_state || "—"}</dd>
                      <dt>表演</dt>
                      <dd>{subShot.performance || subShot.content || "—"}</dd>
                      <dt>出场</dt>
                      <dd>{subShot.exit_state || "—"}</dd>
                      <dt>台词</dt>
                      <dd>{subShot.dialogue?.content || subShot.dialogue?.source_content || "—"}</dd>
                    </dl>
                  </div>
                </details>
              ))}
            </div>
          </div>
        </details>
      ))}
    </div>
  );
}
