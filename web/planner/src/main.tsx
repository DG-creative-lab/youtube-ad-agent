import {useEffect, useState} from "react";
import type {MouseEvent} from "react";
import {createRoot} from "react-dom/client";
import {PerformanceReview} from "./PerformanceReview";
import {AgentComposer, draftPermissionLabels} from "./AgentComposer";
import type {DraftPermission} from "./AgentComposer";
import {CampaignChat} from "./CampaignChat";
import {CampaignSetup} from "./CampaignSetup";
import {GoogleAdsDelivery} from "./GoogleAdsDelivery";
import type {Conversation, ConversationSummary} from "./CampaignChat";
import type {PlannerOptions} from "./AgentComposer";
import {InstructionTest} from "./InstructionTest";
import type {ReviewSelection} from "./InstructionTest";
import "./planner.css";

type Placement = {id: string; title: string; creative: string; source: string};
type Context = {title: string; creative_ref: string};
type Draft = {
  campaign_id: string;
  revision: number;
  brief: {title: string; contexts: Record<string, Context>};
  placements: Placement[];
  instruction_test?: {
    review_id: string; source_revision: number; creative_version: string; source_test_id?: string;
    before: string; after: string; reason: string; measure: string;
    original_viewer_path: string; correction: {label: string; note: string};
    inference?: {mode: string; model: string; prompt_version?: string; evidence_id: string;
      usage: {input_tokens: number | null; output_tokens: number | null; cost_usd: number | null} | null};
  };
};
type PackageReview = {
  package: {
    campaign_id: string;
    revision: number;
    proposed_setup: {objective: string; format: string; budget: string; schedule: string};
    groups: {context: string; title: string; creative_version: string; preview_path: string | null; viewer_path: string}[];
  };
  fingerprint: string;
  current_revision: number;
  blockers: string[];
  history: {revision: number; fingerprint: string; approved_at: string; snapshot_available: boolean}[];
  approval: {actor_id: string; approved_at: string} | null;
};
type Mode = {
  live: boolean;
  googleAdsReporting?: boolean;
  demoRequest: string;
  viewerOrigin: string;
  openrouterReviewModels: string[];
  openrouterDraftModels: string[];
  agentPlanner?: PlannerOptions;
  examples: {creative: string; ref: string; title: string}[];
};
type RunResult = {revision: number; ambiguous: Placement[]; outcome?: string; message?: string; needs_verification?: boolean};
type Run = {
  run_id: string;
  request: string;
  status: "running" | "ready_for_review" | "waiting_for_evidence" | "needs_input" | "answered" | "superseded";
  result?: RunResult | null;
  planner?: {session_id: string; settings: {mode: string; model: string}; draft_permission?: DraftPermission; max_turns: number; turns: unknown[]; routing: {classifier: string}};
  steps: {tool: string; result: unknown}[];
  inference?: {settings: {mode: string; model?: string}};
};

const stepLabels = {
  recommend_delivery_next_test: "Recommend the next test from delivery",
  review_google_ads_delivery: "Review Google Ads delivery",
  load_context: "Load campaign brief",
  propose_placements: "Classify sample placements",
  save_draft: "Save draft revision",
  finish: "Prepare for review",
};
const nextTestStepLabels = {
  load_test_context: "Load review evidence and buyer correction",
  draft_instructions: "Draft revised comparison instructions",
  save_instruction_test: "Save the next test draft",
  finish_test: "Prepare for approval",
};
const instructionReviewStepLabels = {
  load_test_evidence: "Load results for both instruction versions",
  assess_instruction_test: "Assess results and buyer correction",
  save_test_review: "Save the test assessment",
  finish_test_review: "Prepare the assessment for review",
};
type Preparation = {kind: "placement_request"; request: string; model: string; sessionId: string; catalogId: string; afterMessage: number; draftPermission: DraftPermission}
  | {kind: "next_test"; reviewId: string; selection: ReviewSelection}
  | {kind: "experiment_next_test"; testId: string; reviewId: string; selection: ReviewSelection}
  | {kind: "instruction_review"; testId: string; selection: ReviewSelection};
const runKey = "campaign-planner:last-run";
const pendingStartKey = "campaign-planner:pending-start";
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

async function request<T>(path: string, body?: Record<string, unknown>): Promise<T> {
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
  return run && run.status !== "running" ? run.result ?? run.steps.at(-1)?.result as RunResult : null;
}

function App() {
  const [page, setPage] = useState(currentPage);
  const [mode, setMode] = useState<Mode>();
  const [mainModel, setMainModel] = useState("");
  const [placementCatalog, setPlacementCatalog] = useState(() => sessionStorage.getItem("campaign-planner:catalog") ?? "");
  const [conversationId, setConversationId] = useState(() => sessionStorage.getItem("campaign-planner:conversation") || crypto.randomUUID().replaceAll("-", ""));
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [messageText, setMessageText] = useState("");
  const [draftPermission, setDraftPermission] = useState<DraftPermission>("none");
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
  const [deliveryRefresh, setDeliveryRefresh] = useState(0);
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
        const savedModel = sessionStorage.getItem("campaign-planner:model");
        const selectedModel = workspace.agentPlanner?.models.some(item => item.id === savedModel)
          ? savedModel! : workspace.agentPlanner?.default ?? "simulated";
        if (savedModel && selectedModel !== savedModel) {
          const nextConversation = crypto.randomUUID().replaceAll("-", "");
          setConversationId(nextConversation);
          sessionStorage.setItem("campaign-planner:conversation", nextConversation);
        }
        setMainModel(selectedModel);
        sessionStorage.setItem("campaign-planner:model", selectedModel);
        if (!workspace.agentPlanner?.catalogs.some(item => item.id === placementCatalog)) {
          setPlacementCatalog(workspace.agentPlanner?.catalogs[0]?.id ?? "");
        }
          const chats = workspace.live ? [] : await request<ConversationSummary[]>("/api/agent/conversations");
          setConversations(chats);
          const savedConversation = sessionStorage.getItem("campaign-planner:conversation");
          const pendingStart = sessionStorage.getItem(pendingStartKey);
          const restore = chats.find(item => item.id === savedConversation)
            ?? (currentPage() === "/campaign" && !savedConversation && !pendingStart ? chats[0] : undefined);
          if (!workspace.live && restore) {
            await openConversation(restore.id, false);
            setMode(workspace);
            return;
          }
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

  async function prepare(source?: Preparation) {
    if (!mode || mode.live || busy || packageAction) return false;
    if (source && source.kind !== "placement_request" && (!activePackage || needsLatest)) return false;
    const id = !source && !stale && run?.status !== "ready_for_review" && pendingId
      ? pendingId
      : crypto.randomUUID().replaceAll("-", "");
    setPendingId(id);
    sessionStorage.setItem(runKey, id);
    setBusy(true);
    setError("");
    setStale(false);
    if (id !== run?.run_id) setRun(null);
    let starting = false;
    let chatId = source?.kind === "placement_request" ? source.sessionId : run?.planner?.session_id;
    try {
      let current: Run;
      let start: {path: string; body: Record<string, string | number>} | null = null;
      if (source?.kind === "placement_request") {
        start = {path: "/api/agent/placements", body: {
          request: source.request, model: source.model, session_id: source.sessionId,
          run_id: id, catalog_id: source.catalogId, after_message: source.afterMessage,
          draft_permission: source.draftPermission,
        }};
      } else if (source?.kind === "experiment_next_test") {
        start = {path: "/api/agent/experiment-next-test", body: {
          test_id: source.testId, review_id: source.reviewId, ...source.selection,
        }};
      } else if (source?.kind === "instruction_review") {
        start = {path: "/api/agent/instruction-review", body: {
          test_id: source.testId,
          ...source.selection,
        }};
      } else if (source?.kind === "next_test" && activePackage) {
        start = {path: "/api/agent/next-test", body: {
          campaign_id: activePackage.package.campaign_id, revision: activePackage.package.revision,
          fingerprint: activePackage.fingerprint, review_id: source.reviewId,
          ...source.selection,
        }};
      } else if (!stale) {
        const savedStart = sessionStorage.getItem(pendingStartKey);
        if (savedStart) start = JSON.parse(savedStart);
      }
      if (start) {
        if (start.path === "/api/agent/placements") chatId = String(start.body.session_id);
        sessionStorage.setItem(pendingStartKey, JSON.stringify(start));
        starting = true;
        current = await request<Run>(start.path, start.body);
        starting = false;
        sessionStorage.removeItem(pendingStartKey);
      } else if (id === pendingId && !stale) {
        current = await request<Run>("/api/agent/run?id=" + encodeURIComponent(id));
      } else {
        const demoStart = {path: "/api/agent/run", body: {run_id: id, request: mode.demoRequest}};
        sessionStorage.setItem(pendingStartKey, JSON.stringify(demoStart));
        starting = true;
        current = await request<Run>(demoStart.path, demoStart.body);
        starting = false;
        sessionStorage.removeItem(pendingStartKey);
      }
      setPendingId(current.run_id);
      if (current.planner) chatId = current.planner.session_id;
      sessionStorage.setItem(runKey, current.run_id);
      for (let step = current.steps.length; current.status === "running" && step < 12; step++) {
        setRun(current);
        current = await request<Run>("/api/agent/run", {run_id: current.run_id});
      }
      const result = review(current);
      if (result) setDraft(await request<Draft>("/api/campaign"));
      setRun(current);
      return true;
    } catch (failure) {
      if (failure instanceof RequestError && [400, 403, 404, 409].includes(failure.status)) {
        sessionStorage.removeItem(pendingStartKey);
        if (starting || failure.status === 404) {
          sessionStorage.removeItem(runKey);
          setPendingId(null);
          setRun(null);
        }
      }
      setStale(failure instanceof RequestError && failure.status === 409);
      setError(failure instanceof Error ? failure.message : "Could not prepare the campaign.");
      return false;
    } finally {
      if (chatId) {
        try {await refreshConversation(chatId);} catch (failure) {
          if (!(failure instanceof RequestError && failure.status === 404)) {
            setError(previous => previous || "Could not refresh saved messages. Reload before sending another message.");
          }
        }
      }
      setBusy(false);
    }
  }

  async function refreshConversation(id: string) {
    const [chat, chats] = await Promise.all([
      request<Conversation>("/api/agent/conversation?id=" + encodeURIComponent(id)),
      request<ConversationSummary[]>("/api/agent/conversations"),
    ]);
    setConversation(chat);
    setConversations(chats);
  }

  function newConversation(model = mainModel, preserveText = false) {
    setMainModel(model);
    sessionStorage.setItem("campaign-planner:model", model);
    const id = crypto.randomUUID().replaceAll("-", "");
    setConversationId(id);
    sessionStorage.setItem("campaign-planner:conversation", id);
    sessionStorage.removeItem(runKey);
    sessionStorage.removeItem(pendingStartKey);
    setConversation(null);
    setDraftPermission("none");
    setRun(null);
    setPendingId(null);
    if (!preserveText) setMessageText("");
    setStale(false);
    setError("");
    return id;
  }

  async function openConversation(id: string, navigateToWorkspace = true) {
    if (busy || packageAction) return;
    setBusy(true);
    setError("");
    try {
      const [chat, currentDraft] = await Promise.all([
        request<Conversation>("/api/agent/conversation?id=" + encodeURIComponent(id)),
        request<Draft>("/api/campaign"),
      ]);
      const latest = chat.latest_run_id
        ? await request<Run>("/api/agent/run?id=" + encodeURIComponent(chat.latest_run_id)) : null;
      setConversation(chat);
      setDraftPermission("none");
      setDraft(currentDraft);
      setConversationId(id);
      setMainModel(chat.settings.model);
      setRun(latest);
      setPendingId(chat.latest_run_id);
      setMessageText("");
      setStale(false);
      const catalog = chat.messages.at(-1)?.catalog_id;
      if (catalog) {
        setPlacementCatalog(catalog);
        sessionStorage.setItem("campaign-planner:catalog", catalog);
      }
      sessionStorage.setItem("campaign-planner:conversation", id);
      sessionStorage.setItem("campaign-planner:model", chat.settings.model);
      if (chat.latest_run_id) sessionStorage.setItem(runKey, chat.latest_run_id);
      // A failed start's original payload must remain available when restoring that same run.
      const pendingStart = sessionStorage.getItem(pendingStartKey);
      if (pendingStart && JSON.parse(pendingStart).body?.run_id !== chat.latest_run_id) sessionStorage.removeItem(pendingStartKey);
      if (navigateToWorkspace) navigate("/campaign");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not open the conversation.");
    } finally {
      setBusy(false);
    }
  }

  function chooseModel(value: string) {
    newConversation(value, true);
  }
  async function startPlacement(request: string, catalogId: string, permission: DraftPermission) {
    sessionStorage.setItem("campaign-planner:conversation", conversationId);
    navigate("/campaign");
    const pending = sessionStorage.getItem(pendingStartKey);
    if (pending) {
      const saved = JSON.parse(pending);
      if (saved.path === "/api/agent/placements" && saved.body.session_id === conversationId
          && saved.body.request === request && saved.body.catalog_id === catalogId && saved.body.model === mainModel
          && (saved.body.draft_permission ?? "none") === permission) {
        return prepare();
      }
    }
    return prepare({kind: "placement_request", request, model: mainModel, sessionId: conversationId, catalogId,
                    afterMessage: conversation?.latest_message ?? 0, draftPermission: permission});
  }
  const inheritedModel = mode?.agentPlanner?.models.find(item => item.id === mainModel)?.mode === "openrouter"
    ? {mode: "openrouter" as const, model: mainModel} : {mode: "offline" as const};
  const composer = mode?.agentPlanner && <AgentComposer options={mode.agentPlanner} model={mainModel}
    catalogId={placementCatalog} onCatalogId={id => {setPlacementCatalog(id); sessionStorage.setItem("campaign-planner:catalog", id);}}
    followup={Boolean(conversation?.messages.length)} text={messageText} onText={setMessageText}
    draftPermission={draftPermission} onDraftPermission={setDraftPermission}
    onModel={chooseModel} onSubmit={startPlacement} busy={busy || !!packageAction} request={request}
    onCatalogs={catalogs => setMode(current => current?.agentPlanner
      ? {...current, agentPlanner: {...current.agentPlanner, catalogs}} : current)} />;
  const result = review(run);
  const waiting = run?.status === "waiting_for_evidence";
  const waitPlanned = (run?.steps[0]?.result as {next_action?: string} | undefined)?.next_action === "wait";
  const reviewingTest = run?.request === "Review the original and revised instruction test.";
  const activitySteps = reviewingTest ? instructionReviewStepLabels
    : waitPlanned ? {load_test_context: "Load experiment assessment and buyer correction", wait_for_evidence: "Wait for more evidence"}
    : run?.request === "Prepare revised comparison instructions." ? nextTestStepLabels : stepLabels;
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
    if (!mode || result || busy) return;
    if (pendingId && !stale) {
      void prepare();
    } else {
      const sessionId = newConversation("simulated");
      void prepare({kind: "placement_request", request: mode.demoRequest, model: "simulated", sessionId,
                    catalogId: placementCatalog || mode.agentPlanner?.catalogs[0]?.id || "", afterMessage: 0, draftPermission: "placements"});
    }
  }

  return (
    <div className="app">
      <aside className="rail">
        <div className="identity"><span className="mark" aria-hidden="true" />DG Creative Lab</div>
        <nav aria-label="Workspace">
          <span className="rail-label">Workspace</span>
          <a className="new-request" href="/" onClick={event => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            if (!busy && !packageAction) {newConversation(); navigate("/");}
          }}
             aria-current={home ? "page" : undefined}><span aria-hidden="true">+</span> New request</a>
          <a href="/campaign" onClick={event => follow(event, "/campaign")}
             aria-current={!home ? "page" : undefined}>Campaign</a>
          <a href="/placements">Placements <span aria-hidden="true">↗</span></a>
        </nav>
        {conversations.length > 0 && <label className="saved-conversations">Saved conversations
          <select aria-label="Saved conversations" value={conversation?.id ?? ""} disabled={busy || !!packageAction}
            onChange={event => {if (event.target.value) void openConversation(event.target.value);}}>
            <option value="">Choose a conversation</option>
            {conversations.map(chat => <option key={chat.id} value={chat.id}>{chat.title}</option>)}
          </select>
        </label>}
        <div className="rail-footer">Campaign workspace</div>
      </aside>
      <main>
        <div className="topline">
          <span>Workspace <span className="crumb-separator" aria-hidden="true">›</span> {home ? "New request" : "Campaign"}</span>
          {mode && <span className="mode">{mode.live ? "Live catalog"
            : run?.planner ? "Campaign agent" : run?.inference?.settings.mode === "openrouter" ? "Sample campaign" : "Offline sample"}</span>}
        </div>
        {home ? (
          <div className="home">
            <section className="intake" aria-labelledby="page-heading">
              <h1 id="page-heading" tabIndex={-1}>What would you like to prepare?</h1>
              <p className="intake-intro">Describe the campaign task. Your agent chooses tools and prepares a draft for review.</p>
              {composer}
              {error && mode && <p className="error" role="alert">{error}</p>}
              {mode && !mode.live && (
                <>
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
                  <h2 id="request-heading">Conversation</h2>
                  <CampaignChat conversation={conversation} busy={busy} />
                  {composer}
                  {mode && !mode.live && pendingId && !result && <button onClick={() => void prepare()} disabled={busy || !!packageAction}>{action}</button>}
                  {waiting && <p role="status" className="revision">Waiting for more evidence. {result?.message}</p>}
                  {busy && <p className="compact-progress" role="status">
                    {Object.entries(activitySteps).find(([tool]) => !completed.has(tool))?.[1] ?? "Loading the saved draft"}
                  </p>}
                  {!mode && !error && <p role="status">Loading the workspace…</p>}
                  {error && <p className="error" role="alert">{error}</p>}
                </section>
                <section aria-labelledby="draft-heading" className="draft">
                  <span className="label">02 / Review</span>
                  <h2 id="draft-heading">Campaign draft</h2>
                  {draft && <p className="revision">Revision {draft.revision} · {draft.placements.length} placements</p>}
                  {draft?.instruction_test && <section className="context" aria-labelledby="instruction-test-heading">
                    <h3 id="instruction-test-heading">Revised comparison instructions</h3>
                    <p className="revision">Prepared from revision {draft.instruction_test.source_revision},
                      {" review "}{draft.instruction_test.review_id.slice(0, 8)}.</p>
                    {draft.instruction_test.source_test_id && <p className="revision">
                      Based on experiment {draft.instruction_test.source_test_id.slice(0, 8)}.
                      The current approved comparison is the baseline; this does not declare a winning version.
                    </p>}
                    <p className="revision">{draft.instruction_test.reason}</p>
                    <dl className="setup-details">
                      <div><dt>Original</dt><dd>{draft.instruction_test.before}</dd></div>
                      <div><dt>Proposed</dt><dd>{draft.instruction_test.after}</dd></div>
                      <div><dt>Buyer correction</dt><dd>{draft.instruction_test.correction.label}.
                        {draft.instruction_test.correction.note && ` ${draft.instruction_test.correction.note}`}</dd></div>
                      <div><dt>Measure</dt><dd>{draft.instruction_test.measure}</dd></div>
                    </dl>
                    {mode && <a className="text-action" href={mode.viewerOrigin + draft.instruction_test.original_viewer_path}>
                      Open original comparison <span aria-hidden="true">↗</span>
                    </a>}
                    <p className="provenance">{draft.instruction_test.inference?.mode === "openrouter"
                      ? `Draft wording · OpenRouter · ${draft.instruction_test.inference.model}`
                      : draft.instruction_test.inference?.mode === "simulated" ? "Draft wording · Simulated main model"
                      : "Draft wording · Recorded model response"}</p>
                    {draft.instruction_test.inference && <details className="evidence">
                      <summary>Draft inference details</summary>
                      <p className="revision">Prompt {draft.instruction_test.inference.prompt_version ?? "unavailable"} · Evidence {draft.instruction_test.inference.evidence_id.slice(0, 12)}</p>
                      <p className="revision">Tokens: {draft.instruction_test.inference.usage?.input_tokens ?? "unknown"} input,
                        {" "}{draft.instruction_test.inference.usage?.output_tokens ?? "unknown"} output · Reported cost: {draft.instruction_test.inference.usage?.cost_usd == null
                          ? "unknown" : `$${draft.instruction_test.inference.usage.cost_usd}`}</p>
                    </details>}
                  </section>}
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
                            draft.placements.some(row => ["creator_supplied", "licensed"].includes(row.source))
                              ? "Ready for approval · Catalog candidates" : "Ready for approval · Fictional placements"}
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
                {activePackage?.approval && !needsLatest && !busy && (
                  <CampaignSetup key={`setup:${activePackage.fingerprint}`} campaignId={activePackage.package.campaign_id}
                    revision={activePackage.package.revision} fingerprint={activePackage.fingerprint} request={request}
                    onSetupChanged={() => setDeliveryRefresh(current => current + 1)}
                    onPackageConflict={message => {
                      setPackageChanged(true);
                      setPackageError(message);
                    }} />
                )}
                {mode && activePackage?.approval && !needsLatest && !busy && (
                  <GoogleAdsDelivery key={`delivery:${activePackage.fingerprint}:${deliveryRefresh}`} campaignId={activePackage.package.campaign_id}
                    viewerOrigin={mode.viewerOrigin} googleAds={Boolean(mode.googleAdsReporting)}
                    revision={activePackage.package.revision} fingerprint={activePackage.fingerprint} request={request}
                    onPackageConflict={message => {
                      setPackageChanged(true);
                      setPackageError(message);
                    }} />
                )}
                {activePackage?.approval && !needsLatest && !busy && (
                  <PerformanceReview key={`performance:${activePackage.fingerprint}`} campaignId={activePackage.package.campaign_id}
                    revision={activePackage.package.revision} fingerprint={activePackage.fingerprint}
                    groups={activePackage.package.groups} request={request}
                    mainModel={inheritedModel}
                    onCorrectionSaved={() => setDeliveryRefresh(current => current + 1)}
                    onPrepareNextTest={(reviewId, selection) => void prepare({kind: "next_test", reviewId, selection})}
                    onPackageConflict={message => {
                      setPackageChanged(true);
                      setPackageError(message);
                    }} />
                )}
                {draft?.instruction_test && activePackage?.approval && !needsLatest && !busy && mode && (
                  <InstructionTest key={`instructions:${activePackage.fingerprint}`} campaignId={activePackage.package.campaign_id}
                    revision={activePackage.package.revision} fingerprint={activePackage.fingerprint}
                    viewerOrigin={mode.viewerOrigin} request={request}
                    mainModel={inheritedModel}
                    onPrepareNextTest={(testId, reviewId, selection) => void prepare({kind: "experiment_next_test", testId, reviewId, selection})}
                    onReview={(testId, selection) => void prepare({kind: "instruction_review", testId, selection})}
                    onPackageConflict={message => {
                      setPackageChanged(true);
                      setPackageError(message);
                    }} />
                )}
              </div>
              <aside className="activity" aria-label="Run details">
                <span className="label">Run details</span>
                <h2>Agent activity</h2>
                <p role="status" className="run-status">
                  {result?.needs_verification ? "Earlier reply needs verification" : run?.status === "superseded" ? "Request superseded by a follow-up" : run?.status === "answered" ? "Reply saved" : run?.status === "needs_input" ? "Agent needs input" : waiting ? "Waiting for more evidence" : result ? (reviewingTest ? "Test assessment saved"
                    : result.revision === draftRevision ? "Draft ready for review" : `Prepared revision ${result.revision}`)
                    : busy ? (reviewingTest ? "Reviewing the instruction test" : "Preparing the campaign")
                    : pendingId && !stale ? "Preparation can be resumed" : "Waiting for a request"}
                </p>
                {run?.planner ? <><p className="revision">Main model · {run.planner.settings.model}<br />
                  Allowed changes · {draftPermissionLabels[run.planner.draft_permission ?? "none"]}<br />
                  Automatic specialist · {run.planner.routing.classifier}<br />
                  {run.planner.turns.length} of {run.planner.max_turns} model turns</p>
                  <ol>{run.steps.map((step, index) => <li key={index} className="done">
                    <span className="step-number" aria-hidden="true">✓</span>{step.tool.replaceAll("_", " ")}
                    {(step.result as {error?: string}).error && <span> · Tool rejected</span>}
                  </li>)}</ol>
                </> : <ol>
                  {Object.entries(activitySteps).map(([tool, label], index) => (
                    <li key={tool} className={completed.has(tool) ? "done" : ""}>
                      <span className="step-number" aria-hidden="true">{completed.has(tool) ? "✓" : index + 1}</span>
                      {label}
                    </li>
                  ))}
                </ol>}
                {result && result.ambiguous.length > 0 && (
                  <details>
                    <summary>{result.ambiguous.length} entries held for review</summary>
                    <ul>{result.ambiguous.map(row => <li key={row.id}>{row.title}</li>)}</ul>
                  </details>
                )}
                <p className="provenance">{run?.planner ? `${run.planner.settings.mode === "simulated" ? "Simulated main model" : "OpenRouter main model"} · Simulated specialist responses`
                  : waiting ? "No draft or drafting inference requested"
                  : run?.inference?.settings.mode === "openrouter"
                  ? `OpenRouter inference · ${run.inference.settings.model} · Fictional placements`
                  : "Recorded model decisions · Fictional catalog"}</p>
              </aside>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
