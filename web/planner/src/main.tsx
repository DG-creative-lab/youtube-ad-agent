import {useEffect, useState} from "react";
import type {MouseEvent} from "react";
import {createRoot} from "react-dom/client";
import "./planner.css";

type Placement = {id: string; title: string; creative: string; source: string};
type Context = {title: string; creative_ref: string};
type Draft = {
  campaign_id: string;
  revision: number;
  brief: {title: string; contexts: Record<string, Context>};
  placements: Placement[];
};
type PackageReview = {
  package: {
    campaign_id: string;
    revision: number;
    proposed_setup: {objective: string; format: string; budget: string; schedule: string};
    groups: {context: string; creative_version: string; preview_path: string | null; viewer_path: string}[];
  };
  fingerprint: string;
  current_revision: number;
  blockers: string[];
  history: {revision: number; fingerprint: string; approved_at: string; snapshot_available: boolean}[];
  approval: {actor_id: string; approved_at: string} | null;
};
type Mode = {
  live: boolean;
  demoRequest: string;
  viewerOrigin: string;
  examples: {creative: string; ref: string; title: string}[];
};
type RunResult = {revision: number; ambiguous: Placement[]};
type Run = {
  run_id: string;
  status: "running" | "ready_for_review";
  steps: {tool: string; result: unknown}[];
};

const stepLabels = {
  load_context: "Load campaign brief",
  propose_placements: "Classify sample placements",
  save_draft: "Save draft revision",
  finish: "Prepare for review",
};
const runKey = "campaign-planner:last-run";
const operatorKey = "placement-review:operator";
type Page = "/" | "/campaign";
const currentPage = (): Page => location.pathname === "/campaign" ? "/campaign" : "/";
const token = new URLSearchParams(location.hash.slice(1)).get("operator");
if (token) {
  sessionStorage.setItem(operatorKey, token);
  history.replaceState(null, "", location.pathname + location.search);
}

class RequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, body?: Record<string, string | number>): Promise<T> {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: {
      "X-Local-Operator": sessionStorage.getItem(operatorKey) ?? "",
      "X-Placement-Review": "campaign",
      ...(body && {"Content-Type": "application/json"}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw new RequestError(result.error, response.status);
  return result;
}

function review(run: Run | null): RunResult | null {
  return run?.status === "ready_for_review" ? run.steps.at(-1)?.result as RunResult : null;
}

function App() {
  const [page, setPage] = useState(currentPage);
  const [mode, setMode] = useState<Mode>();
  const [draft, setDraft] = useState<Draft>();
  const [run, setRun] = useState<Run | null>(null);
  const [pendingId, setPendingId] = useState(() => sessionStorage.getItem(runKey));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [packageReview, setPackageReview] = useState<PackageReview>();
  const [packageAction, setPackageAction] = useState<"approve" | "export" | "reload">();
  const [packageError, setPackageError] = useState("");
  const [packageChanged, setPackageChanged] = useState(false);
  const [reviewRefresh, setReviewRefresh] = useState(0);
  const [historicalSnapshot, setHistoricalSnapshot] = useState<{fingerprint: string; data: unknown}>();
  const [historyError, setHistoryError] = useState("");

  useEffect(() => {
    const restorePage = () => setPage(currentPage());
    window.addEventListener("popstate", restorePage);
    return () => window.removeEventListener("popstate", restorePage);
  }, []);

  useEffect(() => {
    document.title = page === "/" ? "New request · Campaign planner" : "Campaign workspace";
    document.getElementById("page-heading")?.focus();
  }, [page]);

  useEffect(() => {
    async function load() {
      try {
        const [workspace, currentDraft] = await Promise.all([
          request<Mode>("/api/mode"),
          request<Draft>("/api/campaign"),
        ]);
        setDraft(currentDraft);
        const savedId = sessionStorage.getItem(runKey);
        try {
          if (workspace.live || !savedId) return;
          const previous = await request<Run>("/api/agent/run?id=" + encodeURIComponent(savedId));
          setRun(previous);
        } catch (failure) {
          if (!(failure instanceof RequestError && failure.status === 404)) throw failure;
        } finally {
          setMode(workspace);
        }
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : "Could not load the planner.");
      }
    }
    void load();
  }, []);

  const draftRevision = draft?.revision;
  const sampleMode = mode?.live === false;
  useEffect(() => {
    if (page !== "/campaign" || !sampleMode || !draftRevision) return;
    let cancelled = false;
    setPackageReview(undefined);
    setPackageChanged(false);
    setPackageError("");
    request<PackageReview>("/api/campaign/package?revision=" + draftRevision)
      .then(result => {
        if (!cancelled) setPackageReview(result);
      })
      .catch(failure => {
        if (!cancelled) setPackageError(failure instanceof Error ? failure.message : "Could not load package review.");
      });
    return () => { cancelled = true; };
  }, [page, sampleMode, draftRevision, reviewRefresh]);

  const activePackage = packageReview?.package.revision === draftRevision ? packageReview : undefined;
  const needsLatest = packageChanged || Boolean(activePackage && activePackage.current_revision !== draftRevision);

  async function changePackage(action: "approve" | "export") {
    if (!activePackage || packageAction || needsLatest || busy) return;
    const {package: current, fingerprint} = activePackage;
    setPackageAction(action);
    setPackageError("");
    try {
      const payload = {campaign_id: current.campaign_id, revision: current.revision, fingerprint};
      if (action === "approve") {
        setPackageReview(await request<PackageReview>("/api/campaign/approve", payload));
      } else {
        const setup = await request<unknown>("/api/campaign/export", payload);
        const url = URL.createObjectURL(new Blob([JSON.stringify(setup, null, 2) + "\n"],
          {type: "application/json"}));
        const link = document.createElement("a");
        link.href = url;
        link.download = `${current.campaign_id}-r${current.revision}-fictional-setup.json`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (failure) {
      setPackageChanged(failure instanceof RequestError && failure.status === 409);
      setPackageError(failure instanceof Error ? failure.message : "Could not complete the package action.");
    } finally {
      setPackageAction(undefined);
    }
  }

  async function loadLatest() {
    if (packageAction || busy) return;
    setPackageAction("reload");
    try {
      setDraft(await request<Draft>("/api/campaign"));
      setReviewRefresh(value => value + 1);
    } catch (failure) {
      setPackageError(failure instanceof Error ? failure.message : "Could not load the latest draft.");
    } finally {
      setPackageAction(undefined);
    }
  }

  async function viewApprovedSnapshot(revision: number, fingerprint: string) {
    setHistoryError("");
    setHistoricalSnapshot(undefined);
    try {
      const data = await request<unknown>(`/api/campaign/package?revision=${revision}&approval=${fingerprint}`);
      setHistoricalSnapshot({fingerprint, data});
    } catch (failure) {
      setHistoryError(failure instanceof Error ? failure.message : "Could not load the approved snapshot.");
    }
  }

  async function prepare() {
    if (!mode || mode.live || busy || packageAction) return;
    const id = !stale && run?.status !== "ready_for_review" && pendingId
      ? pendingId
      : crypto.randomUUID().replaceAll("-", "");
    setPendingId(id);
    sessionStorage.setItem(runKey, id);
    setBusy(true);
    setError("");
    setStale(false);
    if (id !== run?.run_id) setRun(null);
    try {
      let current = await request<Run>("/api/agent/run", {run_id: id, request: mode.demoRequest});
      for (let step = current.steps.length; current.status === "running" && step < 4; step++) {
        setRun(current);
        current = await request<Run>("/api/agent/run", {run_id: id});
      }
      const result = review(current);
      if (result) setDraft(await request<Draft>("/api/campaign?revision=" + result.revision));
      setRun(current);
    } catch (failure) {
      setStale(failure instanceof RequestError && failure.status === 409);
      setError(failure instanceof Error ? failure.message : "Could not prepare the campaign.");
    } finally {
      setBusy(false);
    }
  }

  const result = review(run);
  const completed = new Set(run?.steps.map(step => step.tool));
  const action = busy ? "Preparing draft…" : !stale && pendingId && !result ? "Resume preparation" : "Prepare draft";
  const home = page === "/";
  const exampleAction = result || busy ? "Open the campaign workspace"
    : pendingId && !stale ? "Resume the offline example" : "Try the offline example";

  function navigate(destination: Page) {
    if (destination !== page) {
      history.pushState(null, "", destination);
      setPage(destination);
    }
  }

  function follow(event: MouseEvent<HTMLAnchorElement>, destination: Page) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(destination);
  }

  function openExample() {
    navigate("/campaign");
    if (!result && !busy) void prepare();
  }

  return (
    <div className="app">
      <aside className="rail">
        <div className="identity"><span className="mark" aria-hidden="true" />DG Creative Lab</div>
        <nav aria-label="Workspace">
          <span className="rail-label">Workspace</span>
          <a className="new-request" href="/" onClick={event => follow(event, "/")}
             aria-current={home ? "page" : undefined}><span aria-hidden="true">+</span> New request</a>
          <a href="/campaign" onClick={event => follow(event, "/campaign")}
             aria-current={!home ? "page" : undefined}>Campaign</a>
          <a href="/placements">Placements <span aria-hidden="true">↗</span></a>
        </nav>
        <div className="rail-footer">Campaign workspace</div>
      </aside>
      <main>
        <div className="topline">
          <span>Workspace <span className="crumb-separator" aria-hidden="true">›</span> {home ? "New request" : "Campaign"}</span>
          {mode && <span className="mode">{mode.live ? "Live catalog" : "Offline sample"}</span>}
        </div>
        {home ? (
          <div className="home">
            <section className="intake" aria-labelledby="page-heading">
              <h1 id="page-heading" tabIndex={-1}>What would you like to prepare?</h1>
              <p className="intake-intro">Start with a campaign request and review the draft your agent prepares.</p>
              {mode && !mode.live && (
                <>
                  <div className="sample-request">
                    <span className="label">Example request</span>
                    <p>{mode.demoRequest}</p>
                  </div>
                  <button className="example-action" onClick={openExample}>
                    {exampleAction} <span aria-hidden="true">↗</span>
                  </button>
                  <p className="sample-note">Fictional placements · Recorded model decisions</p>
                </>
              )}
              {mode?.live && <p className="intake-message">Open the <a href="/placements">placement workspace</a> to work with your catalog.</p>}
              {!mode && !error && <p className="intake-message" role="status">Loading the workspace…</p>}
              {error && !mode && <p className="intake-message error" role="alert">{error}</p>}
            </section>
          </div>
        ) : (
          <div className="workspace">
            <header className="campaign">
              <span className="label">YouTube campaign</span>
              <h1 id="page-heading" tabIndex={-1}>{draft?.brief.title ?? "Campaign workspace"}</h1>
            </header>
            <div className="columns">
              <div className="main-column">
                <section className="request" aria-labelledby="request-heading">
                  <span className="label">01 / Prepare</span>
                  <h2 id="request-heading">Campaign request</h2>
                  {mode && <p>{mode.live ? "Recorded preparation is available in sample mode." : mode.demoRequest}</p>}
                  {mode && !mode.live && <button onClick={prepare} disabled={busy || !!packageAction}>{action}</button>}
                  {busy && <p className="compact-progress" role="status">
                    {Object.entries(stepLabels).find(([tool]) => !completed.has(tool))?.[1] ?? "Loading the saved draft"}
                  </p>}
                  {!mode && !error && <p role="status">Loading the workspace…</p>}
                  {error && <p className="error" role="alert">{error}</p>}
                </section>
                <section aria-labelledby="draft-heading" className="draft">
                  <span className="label">02 / Review</span>
                  <h2 id="draft-heading">Campaign draft</h2>
                  {draft && <p className="revision">Revision {draft.revision} · {draft.placements.length} placements</p>}
                  {activePackage && <dl className="setup-details">
                    {Object.entries(activePackage.package.proposed_setup).map(([label, value]) => (
                      <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
                    ))}
                  </dl>}
                  {draft && Object.entries(draft.brief.contexts).map(([key, context]) => {
                    const rows = draft.placements.filter(placement => placement.creative === key);
                    const example = mode?.examples.find(item => item.creative === context.creative_ref + "-v1");
                    const group = activePackage?.package.groups.find(item => item.context === key);
                    const viewerPath = group?.viewer_path ?? (example && "/viewer?ad=" + encodeURIComponent(example.creative));
                    return (
                      <section className="context" key={key} aria-label={context.title}>
                        <div className="context-heading">
                          <h3>{context.title}</h3>
                          {mode && viewerPath && <a href={mode.viewerOrigin + viewerPath}>
                            Open comparison <span aria-hidden="true">↗</span>
                          </a>}
                        </div>
                        {mode && group?.preview_path && <a className="creative-preview" href={mode.viewerOrigin + group.preview_path}
                            target="_blank" rel="noreferrer">Preview {group.creative_version} ↗</a>}
                        {rows.length ? <ul className="placements">{rows.map(row => (
                          <li key={row.id}><span>{row.title}</span><small>{row.source.replaceAll("_", " ")}</small></li>
                        ))}</ul> : <p className="empty">No placements saved yet.</p>}
                      </section>
                    );
                  })}
                  {sampleMode && draft && <div className="package-actions">
                    {packageError && <p className="error" role="alert">{packageError}</p>}
                    {needsLatest ? (
                      <>
                        <p className="revision">Review the latest revision before approving or exporting.</p>
                        <button onClick={loadLatest} disabled={busy || !!packageAction}>Load latest revision</button>
                      </>
                    ) : activePackage?.blockers.length ? (
                      <>
                        <p className="revision" role="status">Complete the package before approval.</p>
                        <ul className="revision">
                          {activePackage.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}
                        </ul>
                        <button onClick={loadLatest} disabled={busy || !!packageAction}>Refresh package</button>
                      </>
                    ) : activePackage ? (
                      <>
                        <p className="revision" role="status">
                          {activePackage.approval ? `Revision ${draft.revision} approved` :
                            "Ready for approval · Fictional placements"}
                        </p>
                        <div className="package-buttons">
                          {!activePackage.approval && <button onClick={() => changePackage("approve")}
                            disabled={busy || !!packageAction}>Approve package</button>}
                          <button onClick={() => changePackage("export")}
                            disabled={busy || !!packageAction || !activePackage.approval}>Export setup</button>
                        </div>
                      </>
                    ) : packageError ? <button onClick={loadLatest} disabled={!!packageAction}>Reload package</button>
                      : <p className="revision" role="status">Loading package review…</p>}
                  </div>}
                  {!!activePackage?.history.length && <details className="approval-history">
                    <summary>Approval history</summary>
                    <ul>
                      {activePackage.history.map(entry => <li key={entry.fingerprint}>
                        <p>Revision {entry.revision} · {new Date(entry.approved_at).toLocaleString()} · {entry.fingerprint.slice(0, 8)}</p>
                        {entry.snapshot_available ? (
                          <button onClick={() => viewApprovedSnapshot(entry.revision, entry.fingerprint)}>
                            View approved snapshot
                          </button>
                        ) : <p className="revision">Approved before snapshots were recorded.</p>}
                        {historicalSnapshot?.fingerprint === entry.fingerprint && (
                          <pre className="approval-snapshot">{JSON.stringify(historicalSnapshot.data, null, 2)}</pre>
                        )}
                      </li>)}
                    </ul>
                    {historyError && <p className="error" role="alert">{historyError}</p>}
                  </details>}
                  {draft && <a className="text-action" href="/placements">Manage placements and export URLs <span aria-hidden="true">↗</span></a>}
                </section>
              </div>
              <aside className="activity" aria-label="Run details">
                <span className="label">Run details</span>
                <h2>Agent activity</h2>
                <p role="status" className="run-status">
                  {result ? (result.revision === draftRevision ? "Draft ready for review" : `Prepared revision ${result.revision}`)
                    : busy ? "Preparing the campaign" : pendingId && !stale ? "Preparation can be resumed" : "Waiting for a request"}
                </p>
                <ol>
                  {Object.entries(stepLabels).map(([tool, label], index) => (
                    <li key={tool} className={completed.has(tool) ? "done" : ""}>
                      <span className="step-number" aria-hidden="true">{completed.has(tool) ? "✓" : index + 1}</span>
                      {label}
                    </li>
                  ))}
                </ol>
                {result && result.ambiguous.length > 0 && (
                  <details>
                    <summary>{result.ambiguous.length} entries held for review</summary>
                    <ul>{result.ambiguous.map(row => <li key={row.id}>{row.title}</li>)}</ul>
                  </details>
                )}
                <p className="provenance">Recorded model decisions · Fictional catalog</p>
              </aside>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
