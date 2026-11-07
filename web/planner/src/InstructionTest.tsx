import {useEffect, useState} from "react";

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
    created_at: string;
    evidence: Evidence;
    assessment: {kind: string; title: string; reason: string};
  } | null;
};
type Props = {
  campaignId: string;
  revision: number;
  fingerprint: string;
  viewerOrigin: string;
  request: <T>(path: string, body?: Record<string, string | number>) => Promise<T>;
  onReview: (testId: string) => void;
  onPackageConflict: (message: string) => void;
};

const endpoint = "/api/campaign/instruction-test";
const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});
const label = (arm: string) => arm === "original" ? "Original instructions" : "Revised instructions";

export function InstructionTest({campaignId, revision, fingerprint, viewerOrigin, request,
                                 onReview, onPackageConflict}: Props) {
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
            <button onClick={() => onReview(test.id)} disabled={working}>Review instruction test</button>
          </div>
          {test.evidence.correction && <p className="revision">
            Current buyer correction · {test.evidence.correction.label}. {test.evidence.correction.note}
          </p>}
          {test.review && <section className="context" aria-labelledby="instruction-test-assessment" aria-live="polite">
            <h3 id="instruction-test-assessment">
              {test.needs_review ? "Saved assessment · Review again" : "Agent assessment"}
            </h3>
            {test.needs_review && <p className="revision">
              Activity or the buyer correction has changed since this assessment. Review the test again to update it.
            </p>}
            <h3>{test.review.assessment.title}</h3>
            <p className="revision">{test.review.assessment.reason}</p>
            <p className="revision">Based on {test.review.evidence.rows.map(row =>
              `${row.completions} of ${row.arrivals} completed for ${row.arm} instructions`).join(" and ")}.</p>
            {test.review.evidence.correction && <p className="revision">
              Buyer correction used · {test.review.evidence.correction.label}. {test.review.evidence.correction.note}
            </p>}
            <p className="provenance">Saved {new Date(test.review.created_at).toLocaleString()} · Offline assessment ·
              Illustrative threshold of {test.review.evidence.minimum_per_version} assigned visits per version</p>
          </section>}
        </>
      )}
    </section>
  );
}
