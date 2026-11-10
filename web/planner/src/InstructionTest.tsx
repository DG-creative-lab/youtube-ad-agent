import {useEffect, useState} from "react";

export type ReviewSelection = {mode: "offline"; operation_id: string}
  | {mode: "openrouter"; model: string; operation_id: string};
type Inference = {
  mode: string; model: string; response_model?: string | null; request_id?: string | null;
  prompt_version: string; evidence_id: string;
  usage: {input_tokens: number | null; output_tokens: number | null; cost_usd: number | null};
};

type Correction = {id: string; label: string; note: string};
type Observation = {arm: string; arrivals: number; completions: number; completion_rate: number | null};
type Evidence = {rows: Observation[]; correction: Correction | null; minimum_per_version: number};
const evidenceCohorts = {
  participant: "Participant",
  rehearsal: "Rehearsal",
  fixture: "Authored fixture",
  unknown: "Unknown source",
} as const;
type CohortCounts = {mature_arrivals: number; completions: number; unresolved: number};
type EvidenceSnapshot = {
  id: string;
  cutoff_ms: number;
  rows: {arm: string; cohorts: Record<keyof typeof evidenceCohorts, CohortCounts>}[];
};
type EvidenceDecision = {action: "unavailable"; reason: "unpinned_policy"}
  | {action: "unavailable"; reason: "model_visit_limit"; model_visit_limit: number} | {
  snapshot_id: string;
  action: "reuse" | "keep" | "collect" | "continue_batch" | "wait_batch" | "wait_for_evidence" | "refresh_snapshot";
  probability_worthwhile: number;
  mean_lift: number;
  batch_gain: number | null;
  batch_status: "no_allowance" | "sample_cap" | "initial_sample_pending" | "evaluated" | "in_progress" | "no_batch_recommendation";
  batch_size: number | null;
  batch_remaining: number | null;
  batch_checkpoint_id: string | null;
  sample_cap: number | null;
  assigned: number;
  action_values: {reuse: number; keep: number};
  policy: {
    version: string; minimum_lift: number; prior_alpha: number; prior_beta: number;
    reuse_if_worthwhile: number; reuse_otherwise: number; keep_if_worthwhile: number; keep_otherwise: number;
    batch_cost: number;
  };
};
type Test = {
  id: string;
  started_at: string;
  viewer_path: string;
  evidence: Evidence;
  unknown_source_rows: Observation[];
  evidence_protocol?: {observation_window_ms: number};
  evidence_snapshot: EvidenceSnapshot | null;
  evidence_decision: EvidenceDecision | null;
  needs_review: boolean;
  review: {
    id: string;
    created_at: string;
    evidence: Evidence;
    assessment: {kind: string; title: string; reason: string};
    inference?: Inference;
    assessment_verified?: boolean;
  } | null;
};
type Props = {
  campaignId: string;
  revision: number;
  fingerprint: string;
  viewerOrigin: string;
  limits: InstructionTestLimits;
  request: <T>(path: string, body?: Record<string, string | number | boolean>) => Promise<T>;
  onReview: (testId: string, selection: ReviewSelection) => void;
  mainModel: {mode: "offline"} | {mode: "openrouter"; model: string};
  onPrepareNextTest: (testId: string, reviewId: string, selection: ReviewSelection) => void;
  onPackageConflict: (message: string) => void;
};
export type InstructionTestLimits = {initial: number; batch: number; cap: number; batchCost: number};

const endpoint = "/api/campaign/instruction-test";
const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
const points = new Intl.NumberFormat(undefined, {maximumFractionDigits: 1});
const label = (arm: string) => arm === "original" ? "Original instructions" : "Revised instructions";

function SnapshotDecision({decision}: {decision: EvidenceDecision}) {
  if (decision.action === "unavailable") {
    if (decision.reason === "unpinned_policy") {
      return <p className="revision">This test started without a pinned decision policy. The saved evidence is available without a Bayesian recommendation.</p>;
    }
    return <p className="revision">The offline policy supports up to {decision.model_visit_limit} mature participant visits.</p>;
  }
  const {policy} = decision;
  const initialSamplePending = decision.batch_status === "initial_sample_pending";
  const titles = {
    reuse: "Propose revised wording for reuse",
    keep: "Keep the current wording",
    collect: "Collect one more batch",
    continue_batch: "Extra batch in progress",
    wait_batch: "Wait for batch outcomes",
    wait_for_evidence: initialSamplePending ? "Wait for the initial review point" : "Wait for participant outcomes",
    refresh_snapshot: "Save a fresh snapshot",
  };
  return <section aria-label="Snapshot recommendation">
    <h3>{titles[decision.action]}</h3>
    {decision.action === "refresh_snapshot" && <p>More participant visits arrived after this snapshot. Save a fresh snapshot to check the batch status.</p>}
    {decision.action === "continue_batch" && <p>Remaining participant visits in this batch: {decision.batch_remaining}. Save a fresh snapshot once the batch outcomes resolve.</p>}
    {(decision.action === "wait_batch" || (decision.action === "wait_for_evidence" && !initialSamplePending)) && <p>Save a fresh snapshot once the outstanding participant outcomes resolve.</p>}
    <p className="revision">Estimated lift over the original wording is {points.format(decision.mean_lift * 100)} percentage points.
      The probability of exceeding {points.format(policy.minimum_lift * 100)} points is {percentage.format(decision.probability_worthwhile)}.</p>
    {decision.batch_status === "no_allowance" && <p className="revision">This test has no additional batch allowance.</p>}
    {decision.sample_cap !== null && decision.assigned >= decision.sample_cap && <p className="revision">This test has reached the cap of {decision.sample_cap} participant visits.</p>}
    {initialSamplePending && <p>Save a fresh snapshot once the first {(decision.sample_cap ?? 0) - (decision.batch_size ?? 0)} participant outcomes have resolved.</p>}
    {decision.batch_status === "no_batch_recommendation" && <p className="revision">No saved decision recommended an extra batch at the {(decision.sample_cap ?? 0) - (decision.batch_size ?? 0)}-visit review point.</p>}
    {decision.action !== "refresh_snapshot" && decision.batch_gain !== null && <p className="revision">An additional {decision.batch_size} visits would add {decision.batch_gain.toFixed(3)} expected decision units before the {policy.batch_cost.toFixed(3)} collection cost. The test cap is {decision.sample_cap} participant visits.</p>}
    <details>
      <summary>Decision inputs</summary>
      <p className="revision">Snapshot {decision.snapshot_id.slice(0, 8)} · Policy {policy.version} · Beta({policy.prior_alpha}, {policy.prior_beta}) prior per arm.</p>
      {decision.batch_checkpoint_id && <p className="revision">Snapshot {decision.batch_checkpoint_id.slice(0, 8)} recommended collecting this batch.</p>}
      <p className="revision">For an effect above the target, reuse is worth {policy.reuse_if_worthwhile} units and keep is worth {policy.keep_if_worthwhile}. Otherwise reuse is worth {policy.reuse_otherwise} and keep is worth {policy.keep_otherwise}.</p>
      <p className="revision">Expected value now is {decision.action_values.reuse.toFixed(3)} for reuse and {decision.action_values.keep.toFixed(3)} for keep.</p>
    </details>
  </section>;
}

export function InstructionTest({campaignId, revision, fingerprint, viewerOrigin, request,
                                 limits, onReview, onPackageConflict, mainModel, onPrepareNextTest}: Props) {
  const [test, setTest] = useState<Test | null>(null);
  const [working, setWorking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [allowAdditionalBatch, setAllowAdditionalBatch] = useState(false);
  const query = new URLSearchParams({revision: String(revision), fingerprint}).toString();

  useEffect(() => {
    let cancelled = false;
    request<Test | null>(endpoint + "?" + query)
      .then(result => { if (!cancelled) setTest(result); })
      .catch(failure => { if (!cancelled) setError(failure.message || "Could not load the instruction test."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query, request]);

  async function refresh(action: "read" | "start" | "snapshot" = "read") {
    if (working || loading || (action === "snapshot" && !test)) return;
    const snapshotKey = action === "snapshot" && test ? `instruction-test:snapshot-operation:${test.id}` : null;
    setWorking(true);
    setError("");
    try {
      if (action === "start") {
        await request(endpoint, {campaign_id: campaignId, revision, fingerprint, allow_additional_batch: allowAdditionalBatch});
      }
      if (snapshotKey) {
        const operationId = sessionStorage.getItem(snapshotKey) ?? crypto.randomUUID().replaceAll("-", "");
        sessionStorage.setItem(snapshotKey, operationId);
        await request(endpoint + "/evidence", {
          campaign_id: campaignId, revision, fingerprint, operation_id: operationId,
        });
      }
      setTest(await request<Test | null>(endpoint + "?" + query));
      if (snapshotKey) sessionStorage.removeItem(snapshotKey);
    } catch (failure) {
      if (failure instanceof Error && "status" in failure && failure.status === 409) {
        onPackageConflict(failure.message);
      } else {
        setError(failure instanceof Error ? failure.message : "Could not load the instruction test.");
      }
    } finally {
      setWorking(false);
    }
  }

  function review() {
    if (!test || working) return;
    onReview(test.id, {...mainModel, operation_id: crypto.randomUUID().replaceAll("-", "")});
  }

  const canDraft = test?.review?.assessment.kind === "prepare_another_test";
  function planNextStep() {
    if (!test?.review || test.needs_review || working) return;
    const operation_id = crypto.randomUUID().replaceAll("-", "");
    const selection: ReviewSelection = canDraft ? {...mainModel, operation_id} : {mode: "offline", operation_id};
    onPrepareNextTest(test.id, test.review.id, selection);
  }

  return (
    <section className="performance" aria-labelledby="run-instruction-test">
      <span className="label">04 / Test instructions</span>
      <h2 id="run-instruction-test">Run and review the instruction test</h2>
      {error && <p className="performance-error" role="alert">{error}</p>}
      {loading ? <p className="revision" role="status">Loading the instruction test…</p> : !test ? (
        <>
          <p className="revision">Compare the approved original and revised wording using the same recordings.
            Each browser keeps its assigned version when it returns.</p>
          <p><label><input type="checkbox" checked={allowAdditionalBatch} disabled={working}
            onChange={event => setAllowAdditionalBatch(event.target.checked)} /> Allow one batch of {limits.batch} more participant visits after the first {limits.initial}, up to {limits.cap} total.</label>
            <br /><span className="revision">The offline policy charges {limits.batchCost} decision units for the batch.</span></p>
          <button onClick={() => void refresh("start")} disabled={working}>Run instruction test</button>
          {error && <button onClick={() => void refresh()} disabled={working}>Retry loading test</button>}
        </>
      ) : (
        <>
          <p className="revision">Running since {new Date(test.started_at).toLocaleString()}.
            Participant visits count toward the assessment.</p>
          <div className="package-buttons">
            <a className="text-action" href={viewerOrigin + test.viewer_path + "&rehearsal=1"} target="_blank" rel="noreferrer">
              Rehearse instruction test <span aria-hidden="true">↗</span>
            </a>
            <a className="text-action" href={viewerOrigin + test.viewer_path} target="_blank" rel="noreferrer">
              Open participant link <span aria-hidden="true">↗</span>
            </a>
          </div>
          <dl className="setup-details" aria-label="Current instruction test results">
            {test.evidence.rows.map(row => <div key={row.arm}>
              <dt>{label(row.arm)}</dt>
              <dd>{row.completions} of {row.arrivals} participant visits completed
                <br />{row.completion_rate === null ? "Rate unavailable" : percentage.format(row.completion_rate)}</dd>
            </div>)}
          </dl>
          {test.unknown_source_rows.some(row => row.arrivals > 0) && <>
            <p className="revision">Unknown source · Historical visits</p>
            <dl className="setup-details" aria-label="Unknown source instruction test results">
              {test.unknown_source_rows.map(row => <div key={row.arm}>
                <dt>{label(row.arm)}</dt>
                <dd>{row.completions} of {row.arrivals} visits completed</dd>
              </div>)}
            </dl>
          </>}
          <div className="package-buttons">
            <button onClick={() => void refresh()} disabled={working}>Refresh results</button>
          </div>
          <details className="approval-history" open>
            <summary>Learning evidence</summary>
            {test.evidence_protocol ? <>
              <p className="revision">Participant visits become eligible after {test.evidence_protocol.observation_window_ms / 60000} minutes.
                The snapshot counts completions within that window and shows the other cohorts separately.</p>
              <button onClick={() => void refresh("snapshot")} disabled={working}>Save evidence snapshot</button>
              {test.evidence_snapshot && <div aria-live="polite">
                <p className="revision">Snapshot {test.evidence_snapshot.id.slice(0, 8)} · Cutoff {new Date(test.evidence_snapshot.cutoff_ms).toLocaleString()}</p>
                <dl className="setup-details" aria-label="Saved learning evidence">
                  {test.evidence_snapshot.rows.map(row => <div key={row.arm}>
                    <dt>{label(row.arm)}</dt>
                    {(Object.keys(evidenceCohorts) as (keyof typeof evidenceCohorts)[]).map(source => {
                      const counts = row.cohorts[source];
                      return <dd key={source}>{evidenceCohorts[source]} · {counts.completions} of {counts.mature_arrivals} mature visits completed · {counts.unresolved} unresolved</dd>;
                    })}
                  </div>)}
                </dl>
                {test.evidence_decision && <SnapshotDecision decision={test.evidence_decision} />}
              </div>}
            </> : <p className="revision">Start a new experiment to save evidence with a pinned observation window.</p>}
          </details>
          <div className="performance-controls">
            <p className="revision">Main model · {mainModel.mode === "offline" ? "Recorded offline response" : mainModel.model}</p>
            <button onClick={review} disabled={working}>
              Review instruction test
            </button>
          </div>
          {mainModel.mode === "openrouter" && <p className="revision">
            One request for this review · Up to 512 output tokens · Free model routes with a zero-price cap.
            The model receives the two instructions, results and buyer correction.
          </p>}
          {test.evidence.correction && <p className="revision">
            Current buyer correction · {test.evidence.correction.label}. {test.evidence.correction.note}
          </p>}
          {test.review && <section className="context" aria-labelledby="instruction-test-assessment" aria-live="polite">
            <h3 id="instruction-test-assessment">
              {test.needs_review ? "Saved assessment · Review again" : "Agent assessment"}
            </h3>
            {test.needs_review && <p className="revision">
              {test.review.assessment_verified === false
                ? "This saved assessment needs verification against its evidence. Review the test again to update it."
                : "Activity or the buyer correction has changed since this assessment. Review the test again to update it."}
            </p>}
            <h3>{test.review.assessment.title}</h3>
            <p className="revision">{test.review.assessment.reason}</p>
            {!test.needs_review && <div className="performance-controls">
              <button onClick={planNextStep} disabled={working}>
                Plan next step
              </button>
            </div>}
            {!test.needs_review && <p className="revision">{canDraft
              ? "Prepare another instruction draft using the current approved comparison as the baseline. Approval is separate."
              : "The agent will record that more evidence is needed. No draft or drafting model request will be created."}</p>}
            {test.review.evidence.correction && <p className="revision">
              Buyer correction used · {test.review.evidence.correction.label}. {test.review.evidence.correction.note}
            </p>}
            <p className="provenance">Saved {new Date(test.review.created_at).toLocaleString()} ·
              {test.review.inference?.mode === "openrouter" ? ` OpenRouter · ${test.review.inference.model} · ` : " Offline assessment · "}
              Illustrative threshold of {test.review.evidence.minimum_per_version} participant visits per version</p>
            {test.review.inference && <details className="inference-provenance">
              <summary>Review provenance and usage</summary>
              <p className="revision">
                {test.review.inference.usage.input_tokens ?? "Unknown"} input tokens ·
                {" "}{test.review.inference.usage.output_tokens ?? "Unknown"} output tokens ·
                {" "}{test.review.inference.usage.cost_usd === null ? "Cost unavailable"
                  : `$${test.review.inference.usage.cost_usd} reported cost`}
              </p>
              <p className="revision">Prompt version · {test.review.inference.prompt_version}</p>
              <p className="revision">Evidence reference · {test.review.inference.evidence_id}</p>
              {test.review.inference.response_model && <p className="revision">
                Reported model · {test.review.inference.response_model}
              </p>}
              {test.review.inference.request_id && <p className="revision">
                Provider request · {test.review.inference.request_id}
              </p>}
            </details>}
          </section>}
        </>
      )}
    </section>
  );
}
