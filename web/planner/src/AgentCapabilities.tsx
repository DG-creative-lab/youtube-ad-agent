import {useEffect, useState} from "react";

type Capability = {
  id: string; title: string; description: string;
  kind: "model_tool" | "application_request" | "workspace_action" | "planned";
  state: "available" | "blocked" | "offline_only" | "planned";
  execution_modes: string[]; prerequisites: string[]; reason_codes: string[];
  required_draft_permission: string | null;
};
type Catalogue = {schema_version: number; capabilities: Capability[]};
type Props = {
  scope: string;
  request: <T>(path: string, body?: Record<string, unknown>) => Promise<T>;
  onExample: (text: string) => void;
  disabled: boolean;
};
const states = {available: "Available", blocked: "Blocked · requirements / access", offline_only: "Offline only", planned: "Planned · unavailable"};
const kinds = {model_tool: "Agent tool", application_request: "Application request", workspace_action: "Workspace action", planned: "Planned feature"};
const labels: Record<string, string> = {
  bound_catalog: "A permitted catalog selected for the request", approved_package: "A matching approved package",
  valid_destinations: "Valid destinations", current_activity: "Current viewer activity", bound_instruction_experiment: "An assigned instruction experiment",
  loaded_assigned_evidence: "Loaded evidence for the assigned versions", current_correction: "A current saved buyer correction",
  eligible_current_review: "An eligible current review", keep_takes_correction: "A saved keep-takes correction",
  classified_catalog: "Classified catalog entries", current_revision: "The current campaign revision",
  verified_setup: "A verified setup", current_destinations: "Current destinations", eligible_saved_delivery_report: "An eligible saved delivery report",
  eligible_current_finding: "An eligible current finding", compatible_brief: "A compatible brief", reviewed_creative_brief: "A reviewed creative brief",
  generation_budget: "An authorized generation budget", permitted_assets: "Permitted source assets",
  application: "Application commands", simulated_specialist: "Simulated placement specialist · accuracy unverified",
  simulated_setup: "Simulated paused setup · no live ads", sample_delivery: "Authored sample delivery",
  local_viewer_activity: "Observed local viewer activity", fixed_instruction_components: "Approved neutral instruction components",
  configured_reporting: "Configured reporting · external read", authored_delivery: "Authored sample delivery",
  offline_rehearsal: "Offline delivery rehearsal",
};
const label = (value: string) => labels[value] ?? value.replaceAll("_", " ");
// Examples are composer wording, never dispatch definitions or authority.
const examples: Record<string, string> = {
  read_campaign: "What have we saved in this campaign?",
  classify_catalog: "Find placements for the saved campaign.",
  validate_campaign_setup: "Validate the paused campaign setup.",
  review_performance: "Review this campaign performance.",
  load_experiment_evidence: "Review the assigned instruction experiment.",
  assess_instruction_experiment: "Review the assigned instruction experiment.",
  prepare_next_test: "Review this campaign performance and prepare the next instruction test if the evidence supports it.",
  save_placement_draft: "Find placements for the saved campaign.",
  respond: "What can you do for this campaign?",
  review_google_ads_delivery: "Review Google Ads delivery for this campaign.",
  recommend_delivery_next_test: "Recommend the next test from the saved delivery report.",
};

export function AgentCapabilities({scope, request, onExample, disabled}: Props) {
  const [refresh, setRefresh] = useState(0);
  const [result, setResult] = useState<{scope: string; generation: number; catalogue: Catalogue}>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setResult(undefined);
    setError("");
    void request<Catalogue>("/api/agent/capabilities").then(catalogue => {
      if (catalogue.schema_version !== 1 || !Array.isArray(catalogue.capabilities)) throw new Error("The capability catalogue is unavailable. Refresh to try again.");
      if (active) setResult({scope, generation: refresh, catalogue});
    }).catch(() => {
      if (active) setError("Could not load current capabilities. Refresh to try again.");
    });
    return () => {active = false;};
  }, [scope, refresh, request]);
  const catalogue = result?.scope === scope && result.generation === refresh ? result.catalogue : undefined;
  return <div className="capability-catalogue">
    <div className="capability-heading"><h3>What the agent can help with</h3>
      <button type="button" className="quiet" onClick={() => {setResult(undefined); setError(""); setRefresh(value => value + 1);}}>Refresh capabilities</button>
    </div>
    <p>Current access and configuration only. Requirements are checked again when an action runs. Examples fill your message; sending it and choosing allowed Changes are separate steps.</p>
    <p>Approval, export and launch remain separate workspace actions.</p>
    {!catalogue && !error && <p role="status">Loading current capabilities…</p>}
    {error && <p role="alert" className="error">{error}</p>}
    {catalogue && <ul className="capability-list">{catalogue.capabilities.map(item => <li key={item.id}>
      <details><summary><span className="capability-title">{item.title}</span><span className="capability-state">{states[item.state]}</span></summary>
        <div className="capability-description">
          <span className="label">{kinds[item.kind]}</span><p>{item.description}</p>
          {item.reason_codes.includes("permission_denied") && <p>Unavailable with your current access. A capability example cannot grant access.</p>}
          {item.required_draft_permission && <p>{item.kind === "workspace_action"
            ? "Use the finding's workspace action. It checks current draft access and evidence before preparing an unapproved draft."
            : `To request a draft, choose Changes · ${item.required_draft_permission === "placements" ? "Placement draft" : "Instruction-test draft"} before sending. This catalogue does not grant permission.`}</p>}
          {item.reason_codes.includes("delivery_metrics_unavailable") && <p>Live delivery metrics are unavailable; only the labelled offline rehearsal is supported.</p>}
          {item.execution_modes.length > 0 && <p><strong>Execution:</strong> {item.execution_modes.map(label).join("; ")}.</p>}
          {item.prerequisites.length > 0 && <p><strong>Requirements:</strong> {item.prerequisites.map(label).join("; ")}.</p>}
          {item.kind === "workspace_action" && <p>This action is available in the workspace, rather than as an agent tool.</p>}
          {item.state !== "planned" && item.kind !== "workspace_action" && examples[item.id] && !item.reason_codes.includes("permission_denied") &&
            <button type="button" className="quiet" disabled={disabled} onClick={() => onExample(examples[item.id])}>Use example · {item.title}</button>}
        </div>
      </details>
    </li>)}</ul>}
  </div>;
}
