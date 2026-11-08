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
type Test = {
  id: string;
  started_at: string;
  viewer_path: string;
  evidence: Evidence;
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
  request: <T>(path: string, body?: Record<string, string | number>) => Promise<T>;
  onReview: (testId: string, selection: ReviewSelection) => void;
  mainModel: {mode: "offline"} | {mode: "openrouter"; model: string};
  onPrepareNextTest: (testId: string, reviewId: string, selection: ReviewSelection) => void;
  onPackageConflict: (message: string) => void;
};

const endpoint = "/api/campaign/instruction-test";
const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
const label = (arm: string) => arm === "original" ? "Original instructions" : "Revised instructions";

export function InstructionTest({campaignId, revision, fingerprint, viewerOrigin, request,
                                 onReview, onPackageConflict, mainModel, onPrepareNextTest}: Props) {
  const [test, setTest] = useState<Test | null>(null);
  const [working, setWorking] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const query = new URLSearchParams({revision: String(revision), fingerprint}).toString();

  useEffect(() => {
    let cancelled = false;
    request<Test | null>(endpoint + "?" + query)
      .then(result => { if (!cancelled) setTest(result); })
      .catch(failure => { if (!cancelled) setError(failure.message || "Could not load the instruction test."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query, request]);

  async function refresh(start = false) {
    if (working || loading) return;
    setWorking(true);
    setError("");
    try {
      if (start) {
        await request(endpoint, {campaign_id: campaignId, revision, fingerprint});
      }
      setTest(await request<Test | null>(endpoint + "?" + query));
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
          <button onClick={() => void refresh(true)} disabled={working}>Run instruction test</button>
          {error && <button onClick={() => void refresh()} disabled={working}>Retry loading test</button>}
        </>
      ) : (
        <>
          <p className="revision">Running since {new Date(test.started_at).toLocaleString()}.
            Only visits assigned through this test link count toward its results.</p>
          <a className="text-action" href={viewerOrigin + test.viewer_path} target="_blank" rel="noreferrer">
            Open instruction test <span aria-hidden="true">↗</span>
          </a>
          <dl className="setup-details" aria-label="Current instruction test results">
            {test.evidence.rows.map(row => <div key={row.arm}>
              <dt>{label(row.arm)}</dt>
              <dd>{row.completions} of {row.arrivals} assigned visits completed
                <br />{row.completion_rate === null ? "Rate unavailable" : percentage.format(row.completion_rate)}</dd>
            </div>)}
          </dl>
          <div className="package-buttons">
            <button onClick={() => void refresh()} disabled={working}>Refresh results</button>
          </div>
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
              Illustrative threshold of {test.review.evidence.minimum_per_version} assigned visits per version</p>
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
