import type { FlowStep } from "./autoflowTypes";

type StepTab = {
  id: FlowStep;
  index: string;
  title: string;
  caption: string;
};

type StepTabsProps = {
  steps: StepTab[];
  activeStep: FlowStep;
  completedSteps: Set<FlowStep>;
  canOpenStep: (step: FlowStep) => boolean;
  onChange: (step: FlowStep) => void;
};

export default function StepTabs({ steps, activeStep, completedSteps, canOpenStep, onChange }: StepTabsProps) {
  return (
    <nav className="workflow-nav" aria-label="七步自动流">
      <p className="nav-label">生产流程</p>
      {steps.map((step) => {
        const active = activeStep === step.id;
        const complete = completedSteps.has(step.id);
        return (
          <button
            key={step.id}
            type="button"
            className={`workflow-step ${active ? "active" : ""} ${complete ? "done" : ""}`}
            disabled={!canOpenStep(step.id)}
            onClick={() => onChange(step.id)}
          >
            <span className="step-number">{step.index}</span>
            <span className="step-copy">
              <strong>{step.title}</strong>
              <small>{complete ? "已完成" : step.caption}</small>
            </span>
            <span className="step-dot">{complete ? "✓" : ""}</span>
          </button>
        );
      })}
    </nav>
  );
}
