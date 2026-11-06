import {useEffect, useState} from "react";

type Scenario = {id: string; label: string};
type PerformanceResult = {
  id: string;
  created_at: string;
  sample_delivery: {
    scenario: string;
    label: string;
    source: string;
    grain: string;
    window: {start: string; end: string};
    coverage: string;
    rows: {creative_version: string; metrics: {impressions: number; clicks: number} | null}[];
  };
  local_viewer_activity: {
    source: string;
    window: string;
    rows: {
      creative_version: string;
      comparison_version: string;
      arrivals: number;
      intended_opens: number;
      completions: number;
      completion_rate: number | null;
      unattributed_arrivals: number;
    }[];
  };
  proposal: {
    creative_version: string | null;
    title: string;
    reason: string;
    change: string;
    hold_constant: string;
    measure: string;
  };
};

type Props = {
  campaignId: string;
  revision: number;
  fingerprint: string;
  groups: {creative_version: string; title: string}[];
  request: <T>(path: string, body?: Record<string, string | number>) => Promise<T>;
  onPackageConflict: (message: string) => void;
};

const endpoint = "/api/campaign/performance";
const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});

export function PerformanceReview({campaignId, revision, fingerprint, groups, request, onPackageConflict}: Props) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState("");
  const [result, setResult] = useState<PerformanceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const query = new URLSearchParams({revision: String(revision), fingerprint});
    request<{scenarios: Scenario[]; review: PerformanceResult | null}>(endpoint + "?" + query)
      .then(data => {
        if (cancelled) return;
        setScenarios(data.scenarios);
        setScenario(data.review?.sample_delivery.scenario ?? data.scenarios[0]?.id ?? "");
        setResult(data.review);
      })
      .catch(failure => {
        if (!cancelled) setError(failure.message || "Could not load the performance review.");
      });
    return () => { cancelled = true; };
  }, [revision, fingerprint, request]);

  async function runReview() {
    if (busy || !scenario) return;
    setBusy(true);
    setError("");
    try {
      setResult(await request<PerformanceResult>(endpoint, {campaign_id: campaignId, revision, fingerprint, scenario}));
    } catch (failure) {
      if (failure instanceof Error && "status" in failure && failure.status === 409) {
        onPackageConflict(failure.message);
      } else {
        setError(failure instanceof Error ? failure.message : "Could not review campaign performance.");
      }
    } finally {
      setBusy(false);
    }
  }

  const label = (creative: string) => groups.find(group => group.creative_version === creative)?.title ?? creative;
  const delivery = result?.sample_delivery;
  const activity = result?.local_viewer_activity;
  const proposal = result?.proposal;

  return (
    <section className="performance" aria-labelledby="performance-heading">
      <span className="label">03 / Learn</span>
      <h2 id="performance-heading">Performance review</h2>
      <p className="revision">Review sample delivery alongside observed local viewer activity for revision {revision}.</p>
      <div className="performance-controls">
        <label>Sample delivery scenario
          <select value={scenario} onChange={event => setScenario(event.target.value)} disabled={busy || !scenarios.length}>
            {scenarios.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </label>
        <button onClick={runReview} disabled={busy || !scenario}>{busy ? "Reviewing…" : "Review performance"}</button>
      </div>
      {error && <p className="performance-error" role="alert">{error}</p>}
      {delivery && activity && proposal && (
        <div className="performance-results" aria-busy={busy}>
          <section aria-label="Sample delivery">
            <h3>Sample delivery</h3>
            <p className="revision">{delivery.label} · {delivery.source}</p>
            <p className="revision">{delivery.grain} · {delivery.coverage} coverage</p>
            <p className="revision">{delivery.window.start} to {delivery.window.end} · Fictional dates</p>
            <dl className="setup-details">
              {delivery.rows.map(row => <div key={row.creative_version}>
                <dt>{label(row.creative_version)}</dt>
                <dd>{row.metrics ? `${row.metrics.impressions} impressions · ${row.metrics.clicks} clicks` : "Unknown · Missing from sample report"}</dd>
              </div>)}
            </dl>
          </section>
          <section aria-label="Local viewer activity">
            <h3>Local viewer activity</h3>
            <p className="revision">{activity.source} · {activity.window} for the approved comparison content</p>
            <p className="revision">The completion rate uses verified visits for this content. Local activity is counted separately from sample clicks.</p>
            <dl className="setup-details">
              {activity.rows.map(row => <div key={row.creative_version}>
                <dt>{label(row.creative_version)}</dt>
                <dd>{row.completions} of {row.arrivals} tagged visits completed
                  {row.completion_rate === null ? " · Rate unavailable" : ` · ${percentage.format(row.completion_rate)}`}
                  <br />{row.intended_opens} opened the intended comparison
                  {row.unattributed_arrivals > 0 && <><br />{row.unattributed_arrivals} unattributed {row.unattributed_arrivals === 1 ? "visit" : "visits"} excluded</>}</dd>
              </div>)}
            </dl>
          </section>
          <section aria-label="Proposed next test" aria-live="polite">
            <p className="label">Proposed next test</p>
            <h3>{proposal.title}</h3>
            <p className="revision">
              {proposal.creative_version && `${label(proposal.creative_version)} · `}{proposal.reason}
            </p>
            <dl className="setup-details">
              <div><dt>Try</dt><dd>{proposal.change}</dd></div>
              <div><dt>Keep fixed</dt><dd>{proposal.hold_constant}</dd></div>
              <div><dt>Measure</dt><dd>{proposal.measure}</dd></div>
            </dl>
            <p className="provenance">Offline review · Illustrative decision rules</p>
          </section>
        </div>
      )}
    </section>
  );
}
