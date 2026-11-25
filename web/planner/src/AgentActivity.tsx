import {draftPermissionLabels, modelLabel} from "./AgentComposer";
import type {DraftPermission} from "./AgentComposer";
import type {Selection} from "./openrouter-session";

type Placement = {id: string; title: string; creative: string; source: string};
type Inference = {mode: string; model?: string};
export type RunResult = {
  revision: number; ambiguous: Placement[]; outcome?: string; message?: string; needs_verification?: boolean;
  delivery_report_id?: string | null;
};
export type InferenceTrace = {schema_version: number; run_id: string; status: "running" | "completed" | "failed" | "unknown";
  model: string; provider: string[]; calls: {position: number; state: string; billing_state: string | null;
    code: string | null; message: string | null; http_status: number | null; provider_error_code: number | null; finish_reason: string | null;
    request_id: string | null; input_tokens: number | null; output_tokens: number | null;
    cost_usd: string | null; recorded_duration_ms: number | null}[]};
export type Run = {
  run_id: string;
  request: string;
  diagnostics?: InferenceTrace | null;
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

function saveDiagnostics(trace: InferenceTrace) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(trace, null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = `campaign-run-${trace.run_id}.json`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

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
              {["classify_catalog", "propose_placements"].includes(step.tool) && !rejected && data.route !== "main_model" && <p className="revision">Simulated classification</p>}
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
    {run?.diagnostics && <details className="inference-diagnostics">
      <summary>Run diagnostics · {run.diagnostics.status}</summary>
      <p className="revision">Run {run.run_id}<br />Provider {run.diagnostics.provider.join(", ") || "Not selected"}</p>
      <p className="revision">Protocol and usage metadata only. Prompts, replies, keys and private reasoning are excluded from this diagnostic view.</p>
      <button type="button" className="quiet" onClick={() => saveDiagnostics(run.diagnostics!)}>Save diagnostic JSON</button>
      <ol>{run.diagnostics.calls.map(call => <li key={call.position}>
        <strong>Model call {call.position + 1} · {call.state}</strong>
        {call.message && <p className="error">{call.message}</p>}
        <p className="revision">{call.code && <>Code {call.code}<br /></>}
          HTTP {call.http_status ?? "not recorded"}{call.provider_error_code && <> · Provider error {call.provider_error_code}</>} · Finish {call.finish_reason ?? "not recorded"}<br />
          Input {call.input_tokens ?? "unknown"} · Output {call.output_tokens ?? "unknown"} tokens<br />
          Cost {call.cost_usd === null ? "unconfirmed" : `$${call.cost_usd}`} · Accounting {call.billing_state ?? "not dispatched"}<br />
          Recorded duration {call.recorded_duration_ms === null ? "unknown" : `${call.recorded_duration_ms} ms`}
          {call.request_id && <><br />Provider request {call.request_id}</>}
        </p>
      </li>)}</ol>
    </details>}
    {result?.ambiguous?.length ? <details>
      <summary>{result.ambiguous.length} entries held for review</summary>
      <ul>{result.ambiguous.map(row => <li key={row.id}>{row.title}</li>)}</ul>
    </details> : null}
  </aside>;
}
