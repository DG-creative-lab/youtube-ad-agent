import {draftPermissionLabels, modelLabel} from "./AgentComposer";
import type {DraftPermission} from "./AgentComposer";
import type {Selection} from "./openrouter-session";

type Placement = {id: string; title: string; creative: string; source: string};
type Inference = {mode: string; model?: string};
export type RunResult = {
  revision: number; ambiguous: Placement[]; outcome?: string; message?: string; needs_verification?: boolean;
  delivery_report_id?: string | null;
};
export type Run = {
  run_id: string;
  request: string;
  status: "running" | "ready_for_review" | "waiting_for_evidence" | "needs_input" | "answered" | "superseded";
  result?: RunResult | null;
  planner?: {
    session_id: string;
    settings: {mode: string; model: string} & Partial<Selection>;
    draft_permission?: DraftPermission;
    turns: {position: number; inference: Inference | null}[];
    execution: "application" | "model";
    delivery_demo_scenario: string | null;
  };
  steps: {tool: string; result: unknown}[];
  inference?: {settings: Inference & Partial<Selection>};
};

const toolLabels: Record<string, string> = {
  read_campaign: "Read campaign brief",
  load_context: "Read campaign brief",
  inspect_catalog: "Inspect catalog",
  classify_catalog: "Classify placements",
  propose_placements: "Classify sample placements",
  save_placement_draft: "Save placement draft",
  save_draft: "Save campaign draft",
  ask_clarification: "Ask a question",
  respond: "Reply in conversation",
  validate_campaign_setup: "Validate campaign setup",
  review_google_ads_delivery: "Review Google Ads delivery",
  recommend_delivery_next_test: "Recommend a test from delivery",
  review_performance: "Review campaign performance",
  load_experiment_evidence: "Load experiment evidence",
  assess_instruction_experiment: "Assess the instruction experiment",
  prepare_next_test: "Prepare an instruction-test draft",
  load_test_context: "Load review evidence and buyer correction",
  draft_instructions: "Draft revised instructions",
  save_instruction_test: "Save the instruction-test draft",
  load_test_evidence: "Load results for both instruction versions",
  assess_instruction_test: "Assess results and buyer correction",
  save_test_review: "Save the test assessment",
  wait_for_evidence: "Wait for more evidence",
  finish: "Prepare for review",
  finish_test: "Prepare for approval",
  finish_test_review: "Prepare the assessment for review",
};

const draftTools = new Set(["save_placement_draft", "save_draft", "save_instruction_test", "prepare_next_test", "finish", "finish_test"]);
const evidenceTools = new Set(["review_performance", "load_experiment_evidence", "assess_instruction_experiment", "prepare_next_test", "respond"]);
const deliveryTools = new Set(["review_google_ads_delivery", "recommend_delivery_next_test"]);

function observation(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function executionLabel(inference: Inference) {
  if (inference.mode === "application") return "Application command";
  if (inference.mode === "simulated") return inference.model ? modelLabel(inference.model) : "Offline demo";
  if (inference.mode === "openrouter") return inference.model ? `OpenRouter · ${inference.model}` : "OpenRouter";
  return "Recorded offline workflow";
}

function summarize(step: Run["steps"][number], status: string, data: Record<string, unknown>, draftSaved: boolean) {
  if (status === "Rejected") return "The application declined this action. No change was saved by this step.";
  if (status === "Needs input") return "The agent left a question or a required action in the conversation.";
  if (status === "Waiting for evidence") return "This step needs more evidence before drafting can continue.";
  if (draftSaved) return `Prepared revision ${data.revision} for a separate approval decision.`;
  if (step.tool === "inspect_catalog" && typeof data.shown === "number" && typeof data.total === "number") {
    return `Inspected ${data.shown} of ${data.total} catalog entries.`;
  }
  const assignments = Array.isArray(data.assignments) ? data.assignments : Array.isArray(step.result) ? step.result : null;
  if (assignments && ["classify_catalog", "propose_placements"].includes(step.tool)) {
    const review = assignments.filter(row => {
      const item = observation(row);
      return item.context === "review" || item.creative === "review";
    }).length;
    return `Classified ${assignments.length} entries. ${review} held for review.`;
  }
  if (["read_campaign", "load_context"].includes(step.tool) && typeof data.revision === "number") {
    const placements = typeof data.placement_count === "number" ? data.placement_count : Array.isArray(data.placements) ? data.placements.length : null;
    return `Read revision ${data.revision}.${placements === null ? "" : ` ${placements} existing placements.`}`;
  }
  if (step.tool === "respond") return "Saved a reply in the conversation.";
  if (step.tool === "validate_campaign_setup") return "Validated the simulated campaign setup.";
  if (deliveryTools.has(step.tool) && typeof data.delivery_report_id === "string") return "Used saved delivery and viewer evidence.";
  if (step.tool === "review_performance" || step.tool === "assess_instruction_experiment" || step.tool === "save_test_review") return "Saved an assessment based on the recorded evidence.";
  if (step.tool === "load_experiment_evidence" || step.tool === "load_test_evidence" || step.tool === "load_test_context") return "Loaded the recorded review evidence.";
  if (step.tool === "draft_instructions") return "Prepared revised wording for the instruction test.";
  return "Result recorded with this run.";
}

type Props = {
  run: Run | null;
  result: RunResult | null;
  status: string;
  draftRevision?: number;
  draftApproved?: boolean;
  deliveryRevision?: number;
  evidenceMessageId?: number;
};

export function AgentActivity({run, result, status, draftRevision, draftApproved, deliveryRevision, evidenceMessageId}: Props) {
  const planner = run?.planner;
  const model = planner?.execution === "model" ? planner.settings : run?.inference?.settings;
  const recordedTurns = new Map(planner?.turns.map(turn => [turn.position, turn.inference]));
  return <aside className="activity" aria-labelledby="activity-heading">
    <h2 id="activity-heading" tabIndex={-1}>Agent activity</h2>
    <p role="status" className="run-status">{status}</p>
    {run && <p className="revision">
      {model ? executionLabel(model) : planner ? "Application command" : "Recorded offline workflow"}
      {planner && <><br />Allowed changes · {draftPermissionLabels[planner.draft_permission ?? "none"]}</>}
    </p>}
    {run && run.steps.length > 0 && <ol className="activity-steps">
      {run.steps.map((step, index) => {
        const data = observation(step.result);
        const code = typeof data.reply_code === "string" ? data.reply_code : "";
        const rejected = Boolean(data.error) || code.endsWith("_not_authorized");
        const last = index === run.steps.length - 1;
        const draftSaved = draftTools.has(step.tool) && typeof data.revision === "number"
          && !rejected && (!last || !planner || run.status === "ready_for_review");
        const draftLink = draftSaved && data.revision === draftRevision;
        const stepStatus = rejected ? "Rejected"
          : last && run.status === "waiting_for_evidence" ? "Waiting for evidence"
          : last && run.status === "needs_input" && Boolean(code || step.tool === "ask_clarification") ? "Needs input"
          : draftLink && draftApproved !== undefined ? (draftApproved ? "Approved" : "Awaiting approval")
          : draftSaved ? "Draft saved" : "Completed";
        const inferred = recordedTurns.get(index)
          ?? (!planner && ["assess_instruction_test", "draft_instructions"].includes(step.tool) ? run.inference?.settings : undefined);
        const route = inferred ? executionLabel(inferred) : planner ? "Application command" : "Recorded offline workflow";
        const label = step.tool === "review_google_ads_delivery" && planner?.delivery_demo_scenario
          ? "Review demo delivery" : toolLabels[step.tool] ?? step.tool.replaceAll("_", " ");
        const deliveryLink = deliveryTools.has(step.tool) && typeof data.delivery_report_id === "string"
          && data.revision === deliveryRevision;
        return <li key={`${run.run_id}:${index}`}>
          <details>
            <summary>{label} <span className="step-status">{stepStatus}</span></summary>
            <div className="step-observation">
              <p className="revision">{route}</p>
              {["classify_catalog", "propose_placements"].includes(step.tool) && !rejected && <p className="revision">Simulated classification</p>}
              <p>{summarize(step, stepStatus, data, draftSaved)}</p>
              {draftLink && <a href="#draft-heading">Review revision {data.revision as number}</a>}
              {deliveryLink && <a href="#google-ads-delivery">Open delivery panel</a>}
              {evidenceMessageId !== undefined && evidenceTools.has(step.tool) && !rejected &&
                <a href={`#message-${evidenceMessageId}`}>View evidence in conversation</a>}
            </div>
          </details>
        </li>;
      })}
    </ol>}
    {result?.ambiguous?.length ? <details>
      <summary>{result.ambiguous.length} entries held for review</summary>
      <ul>{result.ambiguous.map(row => <li key={row.id}>{row.title}</li>)}</ul>
    </details> : null}
  </aside>;
}
