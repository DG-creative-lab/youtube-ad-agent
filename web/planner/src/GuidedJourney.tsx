import {useCallback, useEffect, useState} from "react";
import {BriefLearning} from "./BriefLearning";
import type {InstructionReuse} from "./BriefLearning";
import {SnapshotDecision} from "./InstructionTest";
import type {Test} from "./InstructionTest";

type Draft = {campaign_id: string; revision: number; brief: {title: string}; instruction_reuse?: InstructionReuse;
  instruction_test?: {before: string; after: string; original_viewer_path: string}};
type Package = {fingerprint: string; approval: {actor_id: string} | null; blockers: string[];
  history: {revision: number}[]; package: {groups: {title: string; context: string; viewer_path: string;
    content: {title: string; instruction: string}; placements: {title: string; label: string}[]}[]}};
const phases = {plan: "Context and package", wait: "Why the policy waits", learning: "Evidence and reuse"};
type Phase = keyof typeof phases;

export function GuidedJourney() {
  const phase = location.pathname.split("/")[2] as Phase;
  const prefix = `/exercise/${phase}`;
  const [draft, setDraft] = useState<Draft>();
  const [packageReview, setPackageReview] = useState<Package>();
  const [test, setTest] = useState<Test | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const request = useCallback(async <T,>(path: string, body?: Record<string, unknown>): Promise<T> => {
    const response = await fetch(prefix + path, {method: body ? "POST" : "GET", headers: {
      "Content-Type": "application/json", "X-Placement-Review": "campaign",
    }, ...(body ? {body: JSON.stringify(body)} : {})});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not load this exercise. Retry or return to your workspace.");
    return result;
  }, [prefix]);
  const load = useCallback(async () => {
    setError("");
    try {
      const current = await request<Draft>("/api/campaign");
      const reviewed = await request<Package>(`/api/campaign/package?revision=${current.revision}`);
      setDraft(current); setPackageReview(reviewed);
      if (current.instruction_test) {
        setTest(await request<Test | null>(`/api/campaign/instruction-test?revision=${current.revision}&fingerprint=${reviewed.fingerprint}`));
      } else if (phase === "learning") {
        const eligible = current.instruction_reuse ?? await request<InstructionReuse | null>(`/api/campaign/instruction-finding?revision=${current.revision}&fingerprint=${reviewed.fingerprint}`);
        if (eligible) {
          const source = eligible.finding.source_revision;
          const original = await request<Package>(`/api/campaign/package?revision=${source}`);
          setTest(await request<Test | null>(`/api/campaign/instruction-test?revision=${source}&fingerprint=${original.fingerprint}`));
        } else setTest(null);
      } else setTest(null);
      setLoaded(true);
    } catch (failure) {setError(failure instanceof Error ? failure.message : "Could not load this exercise.");}
  }, [request, phase]);
  useEffect(() => {document.title = `${phases[phase] ?? "Learning exercise"} · DG Creative Lab`; void load();}, [load, phase]);
  const reference = draft && packageReview ? {campaign_id: draft.campaign_id, revision: draft.revision, fingerprint: packageReview.fingerprint} : null;
  async function act(path: string) {
    if (!reference || busy) return;
    setBusy(true); setError("");
    try {
      const result = await request<unknown>(path, {...reference, ...(path.endsWith("/evidence") ? {operation_id: crypto.randomUUID().replaceAll("-", "")} : {})});
      if (path.endsWith("/export")) {
        const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {type: "application/json"}));
        const link = document.createElement("a"); link.href = url; link.download = "authored-exercise-handoff.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      await load();
    } catch (failure) {setError(failure instanceof Error ? failure.message : "The exercise action failed.");}
    finally {setBusy(false);}
  }
  return <main className="guided-journey">
    <a href="/campaign">← Return to live workspace</a>
    <p className="label">Authored learning exercise · No live model or ad spend</p>
    <h1>From campaign context to a better next brief</h1>
    <p>Explore three prepared checkpoints. Each has separate saved progress in your invite;
      your campaign and conversations stay in the live workspace.</p>
    <nav aria-label="Learning exercise checkpoints"><ol>{Object.entries(phases).map(([key, title]) =>
      <li key={key}><a href={`/exercise/${key}/`} aria-current={phase === key ? "step" : undefined}>{title}</a></li>)}</ol></nav>
    <p className="provenance">Fictional placements · Bundled synthetic sample voices · Application commands and authored assessments.
      Checkpoint approvals are prepared example history. Exercise outcomes are not observed campaign results.</p>
    <h2>{phases[phase]}</h2>
    {error && <><p role="alert">{error}</p><button type="button" onClick={() => void load()} disabled={busy}>Retry loading checkpoint</button></>}
    {!loaded && !error && <p role="status">Loading the exercise…</p>}
    {draft && packageReview && <>
      <p className="revision">{draft.brief.title} · Revision {draft.revision} · {packageReview.approval ? "Approved example package" : "Unapproved draft — buyer review required"}</p>
      {phase === "plan" && <>
        <p>The same Text to Speech offer needs different proof in each viewing context. Review this prepared placement plan, approve its exact package, then try both comparisons.</p>
        <div className="journey-contexts">{packageReview.package.groups.map(group => <section key={group.context}>
          <h3>{group.title}</h3><p><strong>{group.content.title}</strong></p><p>{group.content.instruction}</p>
          <p className="revision">{group.placements.length} fictional placements. {group.context === "video-editing" ? "Listen for voice timing against the edit." : "Listen for a delivery that fits the passage."}</p>
          <ul>{group.placements.map((placement, index) => <li key={index}>{placement.label}: {placement.title}</li>)}</ul>
          {packageReview.approval && <a href={prefix + group.viewer_path + "&rehearsal=1"} target="_blank" rel="noreferrer">Try {group.title.toLowerCase()} comparison ↗</a>}
        </section>)}</div>
        {!packageReview.approval ? <button type="button" disabled={busy || packageReview.blockers.length > 0} onClick={() => void act("/api/campaign/approve")}>Approve exercise package</button>
          : <button type="button" disabled={busy} onClick={() => void act("/api/campaign/export")}>Download example handoff</button>}
        {packageReview.blockers.map(blocker => <p key={blocker} role="alert">{blocker}</p>)}
        <p>Visits stay in this exercise and do not count as experiment participants. The handoff is for manual campaign setup; it does not launch ads.</p>
        <a className="text-action" href="/exercise/wait/">Next: inspect the empty experiment</a>
      </>}
      {phase === "wait" && <>
        <p>This prepared checkpoint keeps both recordings and changes only the editing instructions. Its approved experiment starts without eligible participant outcomes.</p>
        {draft.instruction_test && <dl className="setup-details"><div><dt>Original wording</dt><dd>{draft.instruction_test.before}</dd></div><div><dt>Revised wording</dt><dd>{draft.instruction_test.after}</dd></div></dl>}
        {draft.instruction_test && <p><a href={prefix + draft.instruction_test.original_viewer_path + "&rehearsal=1"} target="_blank" rel="noreferrer">Try original instructions ↗</a></p>}
        {packageReview.package.groups.filter(group => group.context === "video-editing").map(group => <p key={group.context}><a href={prefix + group.viewer_path + "&rehearsal=1"} target="_blank" rel="noreferrer">Try revised instructions ↗</a></p>)}
        <button type="button" disabled={busy} onClick={() => void act("/api/campaign/instruction-test/evidence")}>Save empty evidence snapshot</button>
        <p>A short session cannot establish lift: participant outcomes must mature within the declared window and reach the initial review point. Rehearsals never supply that evidence.</p>
        <a className="text-action" href="/exercise/learning/">Load authored outcomes: original 2/20, revised 18/20</a>
      </>}
      {phase === "learning" && <>
        <p><strong>Authored experiment example · 2/20 versus 18/20.</strong> These prepared outcomes use the participant protocol to demonstrate the policy; they are not results from your viewers. The example decision and source approvals remain separate from the previous checkpoint.</p>
        <p>The Bayesian estimate updates beliefs about completion, then applies the pinned payoff and collection policy. It proposes wording reuse for buyer review; it does not train the LLM.</p>
        <BriefLearning<Draft> campaignId={draft.campaign_id} revision={draft.revision} fingerprint={packageReview.fingerprint}
          reviewFinding={!draft.instruction_test} applied={draft.instruction_reuse} disabled={busy} request={request}
          onDraft={() => void load()} onReload={() => void load()} />
        <p>Open “Start a fresh brief” and choose Video editing to review the compatible finding. Audiobook briefs cannot inherit this editing result. Preparing wording creates an unapproved draft.</p>
      </>}
      {test && <section>
        <h3>Evidence and policy</h3>
        <p>Completion window: {(test.evidence_protocol?.observation_window_ms ?? 0) / 60000} minutes. A completion requires both takes finished and a choice within this window.</p>
        {test.evidence_snapshot ? <>
          <p className="revision">Authored checkpoint · Experiment {test.id} · Snapshot {test.evidence_snapshot.id} · Cutoff {new Date(test.evidence_snapshot.cutoff_ms).toLocaleString()}</p>
          <dl className="journey-cohorts">{test.evidence_snapshot.rows.map(row => <div key={row.arm}><dt>{row.arm}</dt>{Object.entries(row.cohorts).map(([cohort, counts]) => <dd key={cohort}>{cohort}: {counts.completions}/{counts.mature_arrivals} mature visits · {counts.unresolved} unresolved</dd>)}</div>)}</dl>
          {test.evidence_decision && <SnapshotDecision decision={test.evidence_decision} />}
        </> : <p>No snapshot saved yet. Save the empty snapshot to inspect the wait decision.</p>}
      </section>}
      <details><summary>Historical package approvals</summary><p className="revision">Prepared example history · Approved revisions {packageReview.history.map(item => item.revision).join(", ") || "none"}. Reuse does not change those source approvals.</p></details>
    </>}
    <details className="journey-reset"><summary>Restart this checkpoint</summary>
      <form method="post" action={prefix + "/reset"}><p>This clears only this checkpoint’s saved progress. Other checkpoints and your live workspace are retained.</p>
        <label htmlFor="journey-reset-confirm"><input id="journey-reset-confirm" type="checkbox" name="confirm" value="yes" required /> Reset this checkpoint to its authored starting state</label>
        <button type="submit">Reset checkpoint</button></form></details>
  </main>;
}
