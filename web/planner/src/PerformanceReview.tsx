import {useEffect, useRef, useState} from "react";
import type {ReviewSelection} from "./InstructionTest";

type Scenario = {id: string; label: string};
type Correction = {id: string; kind: string; label: string; note: string; review_id: string};
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
    kind: string;
    creative_version: string | null;
    title: string;
    reason: string;
    change: string;
    hold_constant: string;
    measure: string;
    correction?: Correction;
  };
};

type Props = {
  campaignId: string;
  revision: number;
  fingerprint: string;
  groups: {creative_version: string; title: string}[];
  request: <T>(path: string, body?: Record<string, string | number>) => Promise<T>;
  onPackageConflict: (message: string) => void;
  onPrepareNextTest: (reviewId: string, selection: ReviewSelection) => void;
  mainModel: {mode: "offline"} | {mode: "openrouter"; model: string};
};

const endpoint = "/api/campaign/performance";
const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});

export function PerformanceReview({campaignId, revision, fingerprint, groups, request, onPackageConflict,
                                   onPrepareNextTest, mainModel}: Props) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState("");
  const [result, setResult] = useState<PerformanceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [correctionChoices, setCorrectionChoices] = useState<Scenario[]>([]);
  const [savedCorrection, setSavedCorrection] = useState<Correction | null>(null);
  const [correctionKind, setCorrectionKind] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const correctionOperation = useRef<string | null>(null);

  function prepareNextTest() {
    if (!result) return;
    const operation_id = crypto.randomUUID().replaceAll("-", "");
    onPrepareNextTest(result.id, {...mainModel, operation_id});
  }

  useEffect(() => {
    let cancelled = false;
    const query = new URLSearchParams({revision: String(revision), fingerprint});
    request<{scenarios: Scenario[]; review: PerformanceResult | null; correction: Correction | null;
             correction_choices: Scenario[]}>(endpoint + "?" + query)
      .then(data => {
        if (cancelled) return;
        setScenarios(data.scenarios);
        setScenario(data.review?.sample_delivery.scenario ?? data.scenarios[0]?.id ?? "");
        setResult(data.review);
        setCorrectionChoices(data.correction_choices);
        setSavedCorrection(data.correction);
      })
      .catch(failure => {
        if (!cancelled) setError(failure.message || "Could not load the performance review.");
      });
    return () => { cancelled = true; };
  }, [revision, fingerprint, request]);

  async function runReview() {
    if (busy || saving || !scenario) return;
    setBusy(true);
    setError("");
    try {
      const next = await request<PerformanceResult>(endpoint, {campaign_id: campaignId, revision, fingerprint, scenario});
      setResult(next);
      setSavedCorrection(next.proposal.correction ?? null);
      correctionOperation.current = null;
      setCorrectionKind("");
      setNote("");
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

  async function saveCorrection() {
    if (!result || !correctionKind || saving || busy) return;
    const operation = correctionOperation.current ?? crypto.randomUUID().replaceAll("-", "");
    correctionOperation.current = operation;
    setSaving(true);
    setError("");
    try {
      const saved = await request<Correction>("/api/campaign/correction", {
        campaign_id: campaignId, revision, fingerprint, review_id: result.id, kind: correctionKind, note,
        operation_id: operation,
      });
      setSavedCorrection(saved);
      correctionOperation.current = null;
      setCorrectionKind("");
      setNote("");
    } catch (failure) {
      if (failure instanceof Error && "status" in failure && failure.status === 409) {
        onPackageConflict(failure.message);
      } else {
        setError(failure instanceof Error ? failure.message : "Could not save the buyer correction.");
      }
    } finally {
      setSaving(false);
    }
  }

  const label = (creative: string) => groups.find(group => group.creative_version === creative)?.title ?? creative;
  const delivery = result?.sample_delivery;
  const activity = result?.local_viewer_activity;
  const proposal = result?.proposal;
  const needsRerun = proposal?.correction?.id !== savedCorrection?.id;
  const proposalLabel = needsRerun ? "Saved proposal · Rerun needed" : "Proposed next test";

  return (
    <section className="performance" aria-labelledby="performance-heading">
      <span className="label">03 / Learn</span>
      <h2 id="performance-heading">Performance review</h2>
      <p className="revision">Review sample delivery alongside observed local viewer activity for revision {revision}.</p>
      <div className="performance-controls">
        <label>Sample delivery scenario
          <select value={scenario} onChange={event => setScenario(event.target.value)} disabled={busy || saving || !scenarios.length}>
            {scenarios.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
          </select>
        </label>
        <button onClick={runReview} disabled={busy || saving || !scenario}>{busy ? "Reviewing…" : "Review performance"}</button>
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
          <section aria-label={proposalLabel} aria-live="polite">
            <p className="label">{proposalLabel}</p>
            {needsRerun && <p className="revision">
              {savedCorrection ? (
                <>Current correction · {savedCorrection.label}.
                  {savedCorrection.note && ` ${savedCorrection.note}`}
                  {" Run another review to apply it."}</>
              ) : "The correction used in this review no longer applies. Run another review to get an updated proposal."}
            </p>}
            <h3>{proposal.title}</h3>
            <p className="revision">
              {proposal.creative_version && `${label(proposal.creative_version)} · `}{proposal.reason}
            </p>
            <dl className="setup-details">
              <div><dt>Try</dt><dd>{proposal.change}</dd></div>
              <div><dt>Keep fixed</dt><dd>{proposal.hold_constant}</dd></div>
              <div><dt>Measure</dt><dd>{proposal.measure}</dd></div>
            </dl>
            {proposal.correction && (
              <p className="revision">
                Used buyer correction from review {proposal.correction.review_id.slice(0, 8)}.{" "}
                {proposal.correction.label}. {proposal.correction.note}
              </p>
            )}
            <p className="provenance">Offline review · Illustrative decision rules</p>
            {proposal.correction?.kind === "keep_takes" && <div className="performance-controls">
              <p className="revision">Main model · {mainModel.mode === "offline" ? "Recorded offline response" : mainModel.model}</p>
              <button onClick={prepareNextTest}
                disabled={busy || saving || needsRerun}>
                Prepare next test
              </button>
            </div>}
          </section>
          {proposal.kind === "comparison_test" && (
            <section aria-labelledby="buyer-correction">
              <h3 id="buyer-correction">Buyer correction</h3>
              <p className="revision">Tell the agent what to keep fixed for this comparison.</p>
              <form className="correction-form" onSubmit={event => { event.preventDefault(); void saveCorrection(); }}>
                <label>What should stay unchanged?
                  <select value={correctionKind} onChange={event => {
                    correctionOperation.current = null;
                    setCorrectionKind(event.target.value);
                  }}
                    disabled={busy || saving} required>
                    <option value="">Choose a correction</option>
                    {correctionChoices.map(choice => <option key={choice.id} value={choice.id}>{choice.label}</option>)}
                  </select>
                </label>
                <label>Reason for the correction (optional)
                  <textarea value={note} maxLength={500} rows={2} disabled={busy || saving}
                    onChange={event => {
                      correctionOperation.current = null;
                      setNote(event.target.value);
                    }} />
                </label>
                <button disabled={!correctionKind || busy || saving}>{saving ? "Saving…" : "Save correction"}</button>
              </form>
            </section>
          )}
        </div>
      )}
    </section>
  );
}
