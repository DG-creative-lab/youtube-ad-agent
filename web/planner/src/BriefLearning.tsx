import {useEffect, useState} from "react";
import type {FormEvent} from "react";

const findingPath = "/api/campaign/instruction-finding";
const percent = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});

export type InstructionReuse = {
  finding: {
    id: string;
    test_id: string;
    snapshot_id: string;
    cutoff_ms: number;
    source_revision: number;
    context_title: string;
    model: string;
    before: string;
    after: string;
    decision: {
      arms: {arm: string; completions: number; mature_arrivals: number}[];
      mean_lift: number;
      probability_worthwhile: number;
      policy: {version: string; minimum_lift: number};
    };
  };
  correction: {id: string; label: string; note: string};
};

function FindingEvidence({reuse}: {reuse: InstructionReuse}) {
  const {finding, correction} = reuse;
  const {decision} = finding;
  return <>
    <p>The test used the same {finding.context_title.toLowerCase()} context, recordings, and baseline wording.</p>
    <dl className="setup-details">
      <div><dt>Original wording</dt><dd>{finding.before}</dd></div>
      <div><dt>Proposed wording</dt><dd>{finding.after}</dd></div>
      {decision.arms.map(arm => <div key={arm.arm}>
        <dt>{arm.arm === "original" ? "Original wording" : "Revised wording"}</dt>
        <dd>{arm.completions} of {arm.mature_arrivals} participant visits completed</dd>
      </div>)}
      <div><dt>Buyer correction</dt><dd>{correction.label}. {correction.note}</dd></div>
    </dl>
    <p>Estimated lift is {(decision.mean_lift * 100).toFixed(1)} percentage points.
      The probability of exceeding {decision.policy.minimum_lift * 100} points is {percent.format(decision.probability_worthwhile)}.</p>
    <details>
      <summary>Evidence source</summary>
      <p className="revision">Experiment {finding.test_id.slice(0, 8)} · Revision {finding.source_revision} · Snapshot {finding.snapshot_id.slice(0, 8)}</p>
      <p className="revision">{new Date(finding.cutoff_ms).toLocaleString()} · {finding.model} · {decision.policy.version}</p>
    </details>
  </>;
}

type Props<Draft> = {
  campaignId: string;
  revision: number;
  fingerprint: string;
  reviewFinding: boolean;
  applied?: InstructionReuse;
  disabled: boolean;
  request: <T>(path: string, body?: Record<string, unknown>) => Promise<T>;
  onDraft: (draft: Draft) => void;
  onReload: () => void;
};

export function BriefLearning<Draft>({campaignId, revision, fingerprint, reviewFinding, applied,
                                      disabled, request, onDraft, onReload}: Props<Draft>) {
  const [reuse, setReuse] = useState<InstructionReuse | null>();
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!reviewFinding || applied) return;
    let active = true;
    const query = new URLSearchParams({revision: String(revision), fingerprint});
    request<InstructionReuse | null>(findingPath + "?" + query)
      .then(value => {if (active) setReuse(value);})
      .catch(failure => {if (active) setError(failure.message);});
    return () => {active = false;};
  }, [reviewFinding, applied, revision, fingerprint, request]);

  async function save(path: string, fields: Record<string, unknown>) {
    if (working || disabled) return;
    setWorking(true);
    setError("");
    try {
      const body = {campaign_id: campaignId, revision, fingerprint, ...fields};
      if (path === findingPath + "/retire") {
        await request(path, body);
        setReuse(null);
      } else {
        onDraft(await request<Draft>(path, body));
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the brief change.");
    } finally {
      setWorking(false);
    }
  }

  function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    void save("/api/campaign/brief", {title: form.get("title"), goal: form.get("goal"), context: form.get("context")});
  }

  const shown = applied ?? reuse;
  return <div className="context">
    <details>
      <summary>Start a fresh brief</summary>
      <form className="correction-form" onSubmit={start}>
        <label>Brief title <input name="title" required maxLength={120} /></label>
        <label>Goal <textarea name="goal" required maxLength={500} rows={2} /></label>
        <label htmlFor="fresh-brief-context">Comparison context</label>
        <select id="fresh-brief-context" name="context">
          <option value="video-editing">Video editing</option>
          <option value="audiobook">Audiobook production</option>
        </select>
        <button disabled={disabled || working}>Create brief</button>
      </form>
    </details>
    {shown ? <section aria-label="Saved instruction finding">
      <h3>{applied ? "Wording from a saved finding" : "Reuse tested wording"}</h3>
      <FindingEvidence reuse={shown} />
      {!applied && <div className="package-buttons">
        <button disabled={disabled || working} onClick={() => void save(findingPath + "/apply", {
          finding_id: shown.finding.id, correction_id: shown.correction.id, draft_permission: "instruction_test",
        })}>Prepare wording draft</button>
        <button disabled={disabled || working}
          onClick={() => void save(findingPath + "/retire", {finding_id: shown.finding.id})}>Retire finding</button>
      </div>}
    </section> : reviewFinding && reuse === null && <p className="revision">No current instruction finding applies to this brief.</p>}
    {error && <>
      <p role="alert" className="performance-error">{error}</p>
      <button disabled={disabled || working} onClick={onReload}>Reload brief</button>
    </>}
  </div>;
}
