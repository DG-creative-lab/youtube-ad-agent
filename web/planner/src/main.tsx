import {useEffect, useRef, useState, useSyncExternalStore} from "react";
import type {MouseEvent} from "react";
import {createRoot} from "react-dom/client";
import {PerformanceReview} from "./PerformanceReview";
import {AgentComposer} from "./AgentComposer";
import {activityFailureStatus} from "./activity-status";
import {AgentActivity} from "./AgentActivity";
import type {Run, RunResult} from "./AgentActivity";
import type {DraftPermission} from "./AgentComposer";
import {CampaignChat} from "./CampaignChat";
import {CampaignSetup} from "./CampaignSetup";
import {GoogleAdsDelivery} from "./GoogleAdsDelivery";
import type {Conversation, ConversationSummary} from "./CampaignChat";
import type {PlannerOptions} from "./AgentComposer";
import {InstructionTest} from "./InstructionTest";
import type {InstructionTestLimits, ReviewSelection} from "./InstructionTest";
import {BriefLearning} from "./BriefLearning";
import type {InstructionReuse} from "./BriefLearning";
import {openrouter, request, RequestError, forgetFailedOfflineRun} from "./openrouter-session";
import type {Selection, RunAttempt} from "./openrouter-session";
import {WorkspaceAccount} from "./WorkspaceAccount";
import "../../brand/tokens.css";
import "./planner.css";

type Placement = {id: string; title: string; creative: string; source: string};
type Context = {title: string; creative_ref: string};
type Draft = {
  campaign_id: string;
  revision: number;
  brief: {title: string; contexts: Record<string, Context>};
  placements: Placement[];
  instruction_reuse?: InstructionReuse;
  instruction_test?: {
    review_id: string; source_revision: number; creative_version: string; source_test_id?: string;
    before: string; after: string; reason: string; measure: string;
    original_viewer_path: string; correction: {label: string; note: string};
    inference?: {mode: string; model: string; prompt_version?: string; evidence_id: string;
      usage: {input_tokens: number | null; output_tokens: number | null; cost_usd: number | null} | null};
  };
};
type PackageReview = {
  public_comparisons?: {creative_ref: string; url: string}[];
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
  previewScope?: string;
  workspace?: {actor: string; client_id: string; brand_id: string; id: string; fixture: boolean};
  live: boolean;
  googleAdsReporting?: boolean;
  openrouterAvailable?: boolean;
  liveInference?: boolean;
  instructionTestLimits: InstructionTestLimits;
  demoRequest: string;
  viewerOrigin: string;
  publicViewerOrigin?: string;
  openrouterReviewModels: string[];
  openrouterDraftModels: string[];
  agentPlanner?: PlannerOptions;
  examples: {creative: string; ref: string; title: string}[];
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

function review(run: Run | null): RunResult | null {
  return run && run.status !== "running" ? run.result ?? run.steps.at(-1)?.result as RunResult : null;
}

function App() {
  const account = useSyncExternalStore(openrouter.subscribe, openrouter.snapshot);
  const viewEpoch = useRef(0);
  const pendingProviderStart = useRef<{path: string; body: Record<string, unknown>; uncertain: boolean} | null>(null);
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
  const [runFailure, setRunFailure] = useState<{code: string; message: string} | null>(null);
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
    document.title = `${page === "/" ? "New request" : "Campaign workspace"} · DG Creative Lab`;
    document.getElementById("page-heading")?.focus();
  }, [page]);

  useEffect(() => {
    const startFresh = new URLSearchParams(location.search).get("new") === "1";
    async function load() {
      try {
        const [workspace, currentDraft] = await Promise.all([
          request<Mode>("/api/mode"),
          request<Draft>("/api/campaign"),
        ]);
        const nativeBinding = workspace.workspace ? {actor_id: workspace.workspace.actor, client_id: workspace.workspace.client_id,
          brand_id: workspace.workspace.brand_id, workspace_id: workspace.workspace.id, campaign_id: currentDraft.campaign_id} : null;
        openrouter.bindScope(JSON.stringify([workspace.workspace ?? "local", currentDraft.campaign_id]), nativeBinding);
        if (workspace.workspace) {
          const scope = JSON.stringify([workspace.workspace.actor, workspace.workspace.client_id,
            workspace.workspace.brand_id, workspace.workspace.id, currentDraft.campaign_id]);
          if (sessionStorage.getItem("staff-workspace-scope") !== scope) {
            openrouter.logout();
            openrouter.bindScope(JSON.stringify([workspace.workspace, currentDraft.campaign_id]), nativeBinding);
            for (const key of Object.keys(sessionStorage)) {
              if (key.startsWith("campaign-planner:")) sessionStorage.removeItem(key);
            }
            const nextConversation = crypto.randomUUID().replaceAll("-", "");
            setConversationId(nextConversation);
            sessionStorage.setItem("campaign-planner:conversation", nextConversation);
            setPendingId(null);
            setRun(null); setRunFailure(null);
            setDraftPermission("none");
            sessionStorage.setItem("staff-workspace-scope", scope);
          }
        }
        setDraft(currentDraft);
        const savedModel = sessionStorage.getItem("campaign-planner:model");
        const selectedModel = workspace.liveInference ? "" : workspace.previewScope ? "simulated"
          : workspace.agentPlanner?.models.some(item => item.id === savedModel) ? savedModel!
          : workspace.agentPlanner?.default ?? "simulated";
        if (!workspace.previewScope && savedModel && selectedModel !== savedModel && ["simulated", "simulated-inspect"].includes(savedModel)) {
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
          if (startFresh) {
            newConversation(selectedModel);
            const destination = new URL(location.href);
            destination.searchParams.delete("new");
            history.replaceState(null, "", destination.pathname + destination.search + destination.hash);
            setMode(workspace);
            return;
          }
          const savedConversation = sessionStorage.getItem("campaign-planner:conversation");
          const pendingStart = sessionStorage.getItem(pendingStartKey);
          if (pendingStart) {
            const marker = JSON.parse(pendingStart);
            if (marker.provider && !marker.run_id) {
              setRun(null); setRunFailure(null); setPendingId(null); sessionStorage.removeItem(runKey);
              setError(`The original start receipt is unavailable. Operation ${marker.operation_id} is retained; no replacement request was sent. Saved conversations remain readable.`);
              setMode(workspace); return;
            }
          }
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
          const recordedModel = previous.planner?.settings.model ?? previous.inference?.settings.model;
          if (recordedModel) setMainModel(recordedModel);
          openrouter.hydrate(previous.planner?.settings ?? previous.inference?.settings);
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
        if (mode?.workspace) {
          setPackageReview(await request<PackageReview>(`/api/campaign/package?revision=${current.revision}`));
        }
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
    const epoch = viewEpoch.current;
    const providerEpoch = openrouter.snapshot().epoch;
    const guard = () => {openrouter.assertCurrent(providerEpoch); if (epoch !== viewEpoch.current) throw new RequestError("The conversation changed. Open its saved history to continue.", 409, "client_context_changed");};
    const id = !source && pendingId ? pendingId : crypto.randomUUID().replaceAll("-", "");
    setBusy(true); setError(""); setRunFailure(null); setStale(false);
    const originalSettings = run?.planner?.settings ?? run?.inference?.settings;
    const attempt: RunAttempt = {kind: originalSettings?.mode === "openrouter" ? "provider" : originalSettings ? "offline" : "unknown",
      phase: "read", acknowledged: run?.run_id === id};
    let chatId = source?.kind === "placement_request" ? source.sessionId : run?.planner?.session_id;
    try {
      let current: Run;
      let start: {path: string; body: Record<string, unknown>} | null = null;
      if (source?.kind === "placement_request") {
        const remote = !["simulated", "simulated-inspect"].includes(source.model);
        const chosen = openrouter.snapshot().selection;
        if (remote && (!mode.openrouterAvailable || !chosen || chosen.profile !== "planner" || chosen.model !== source.model || !openrouter.canUse(chosen))) {
          throw new RequestError("Reconnect and select an eligible planner model before sending. Your typed text is retained.", 409, "waiting_for_credentials");
        }
        start = {path: "/api/agent/placements", body: {
          request: source.request, model: source.model, session_id: source.sessionId,
          run_id: id, catalog_id: source.catalogId, after_message: source.afterMessage,
          draft_permission: source.draftPermission, ...(remote && {provider_selection_id: chosen!.selection_id}),
        }};
      } else if (source) {
        const selection = source.selection.mode === "openrouter"
          ? {mode: "openrouter", operation_id: source.selection.operation_id,
             provider_selection_id: (await openrouter.structured(source.selection.model)).selection_id}
          : source.selection;
        guard();
        if (source.kind === "experiment_next_test") start = {path: "/api/agent/experiment-next-test", body: {test_id: source.testId, review_id: source.reviewId, ...selection}};
        else if (source.kind === "instruction_review") start = {path: "/api/agent/instruction-review", body: {test_id: source.testId, ...selection}};
        else if (activePackage) start = {path: "/api/agent/next-test", body: {campaign_id: activePackage.package.campaign_id,
          revision: activePackage.package.revision, fingerprint: activePackage.fingerprint, review_id: source.reviewId, ...selection}};
      } else {
        const saved = sessionStorage.getItem(pendingStartKey);
        if (saved) {
          const pending = JSON.parse(saved);
          attempt.kind = pending.provider ? "provider" : "offline";
          if (pending.provider) {
            // Only a known run can recover a lost start receipt. Never reconstruct a provider payload from browser storage.
            if (!pending.run_id) throw new RequestError("The original start receipt is unavailable. Operation " + pending.operation_id + " is retained; no replacement request was sent.", 409, "inference_outcome_unknown");
          } else start = pending;
        }
      }
      if (start) {
        const remote = !!start.body.provider_selection_id;
        attempt.kind = remote ? "provider" : "offline"; attempt.phase = "start"; attempt.acknowledged = false;
        if (start.path === "/api/agent/placements") chatId = String(start.body.session_id);
        sessionStorage.setItem(pendingStartKey, openrouter.serializeStart(start));
        if (remote) {
          pendingProviderStart.current = {...start, uncertain: true};
          if (!start.body.run_id) {setPendingId(null); setRun(null); setRunFailure(null); sessionStorage.removeItem(runKey);}
        }
        if (start.body.run_id) {setPendingId(String(start.body.run_id)); sessionStorage.setItem(runKey, String(start.body.run_id)); if (run?.run_id !== start.body.run_id) setRun(null); setRunFailure(null);}
        current = await request<Run>(start.path, start.body, remote); guard();
        sessionStorage.removeItem(pendingStartKey); pendingProviderStart.current = null;
      } else if (pendingId) {
        current = await request<Run>("/api/agent/run?id=" + encodeURIComponent(pendingId)); guard();
        sessionStorage.removeItem(pendingStartKey); pendingProviderStart.current = null;
      } else {
        attempt.kind = "offline"; attempt.phase = "start"; attempt.acknowledged = false;
        const demoStart = {path: "/api/agent/run", body: {run_id: id, request: mode.demoRequest}};
        sessionStorage.setItem(pendingStartKey, JSON.stringify(demoStart));
        current = await request<Run>(demoStart.path, demoStart.body); guard(); sessionStorage.removeItem(pendingStartKey);
      }
      attempt.acknowledged = true; attempt.phase = "advance";
      setPendingId(current.run_id); sessionStorage.setItem(runKey, current.run_id);
      if (current.planner) chatId = current.planner.session_id;
      setRun(current);
      for (let step = 0; current.status === "running" && step < 12; step++) {
        const settings = current.planner?.settings ?? current.inference?.settings;
        try {
          // Receipt and non-inference recovery is always tried without a key first.
          current = await request<Run>("/api/agent/run", {run_id: current.run_id});
        } catch (failure) {
          guard();
          if (!(failure instanceof RequestError && failure.code === "waiting_for_credentials") || !openrouter.canUse(settings)) throw failure;
          current = await request<Run>("/api/agent/run", {run_id: current.run_id}, true);
        }
        guard(); setRun(current);
      }
      if (review(current)) {const latest = await request<Draft>("/api/campaign"); guard(); setDraft(latest);}
      setRun(current); return true;
    } catch (failure) {
      if (epoch !== viewEpoch.current || failure instanceof RequestError && failure.code === "client_context_changed") return false;
      // A definitive denied offline start has no saved run to resume. Saved/provider/uncertain operations keep their original identity.
      if (forgetFailedOfflineRun(failure, attempt)) {
        sessionStorage.removeItem(pendingStartKey); sessionStorage.removeItem(runKey);
        setPendingId(null); setRun(null); setRunFailure(null); setStale(false);
      }
      // Refresh the owned run without a key. This reads saved diagnostics and
      // cannot repeat inference, even after an uncertain provider response.
      const failedRunId = sessionStorage.getItem(runKey);
      if (failedRunId) {
        try {const saved = await request<Run>("/api/agent/run?id=" + encodeURIComponent(failedRunId)); guard(); setRun(saved);}
        catch { /* Keep the original failure if its diagnostic read is unavailable. */ }
      }
      setRunFailure({code: failure instanceof RequestError ? failure.code : "request_outcome_unavailable",
        message: failure instanceof Error ? failure.message : "The request outcome is unavailable."});
      const lostStructuredStart = pendingProviderStart.current;
      setError(lostStructuredStart && !lostStructuredStart.body.run_id
        ? `The original start receipt is unavailable. Operation ${lostStructuredStart.body.operation_id} is retained; no replacement request was sent. Saved conversations remain readable.`
        : failure instanceof Error ? failure.message : "The request outcome is unavailable. Open saved history before continuing.");
      return false;
    } finally {
      if (epoch === viewEpoch.current) {
        if (chatId) {try {await refreshConversation(chatId, epoch);} catch { /* The original operation remains available through explicit history reads. */ }}
        setBusy(false);
      } else setBusy(false);
    }
  }

  async function refreshConversation(id: string, epoch = viewEpoch.current) {
    const [chat, chats] = await Promise.all([
      request<Conversation>("/api/agent/conversation?id=" + encodeURIComponent(id)),
      request<ConversationSummary[]>("/api/agent/conversations"),
    ]);
    if (epoch !== viewEpoch.current) return;
    setConversation(chat);
    setConversations(chats);
  }

  function newConversation(model = mode?.liveInference ? "" : mode?.previewScope ? "simulated" : mainModel, preserveText = false) {
    viewEpoch.current++;
    pendingProviderStart.current = null;
    setMainModel(model);
    sessionStorage.setItem("campaign-planner:model", model);
    const id = crypto.randomUUID().replaceAll("-", "");
    setConversationId(id);
    sessionStorage.setItem("campaign-planner:conversation", id);
    sessionStorage.removeItem(runKey);
    sessionStorage.removeItem(pendingStartKey);
    setConversation(null);
    setDraftPermission("none");
    setRun(null); setRunFailure(null);
    setPendingId(null);
    if (!preserveText) setMessageText("");
    setStale(false);
    setError("");
    return id;
  }

  async function openConversation(id: string, navigateToWorkspace = true) {
    if (busy || packageAction) return;
    const epoch = ++viewEpoch.current;
    setBusy(true);
    setError("");
    try {
      const [chat, currentDraft] = await Promise.all([
        request<Conversation>("/api/agent/conversation?id=" + encodeURIComponent(id)),
        request<Draft>("/api/campaign"),
      ]);
      const restoreRunId = !navigateToWorkspace ? sessionStorage.getItem(runKey) ?? chat.latest_run_id : chat.latest_run_id;
      const latest = restoreRunId
        ? await request<Run>("/api/agent/run?id=" + encodeURIComponent(restoreRunId)) : null;
      if (epoch !== viewEpoch.current) return;
      setConversation(chat);
      setDraftPermission("none");
      setDraft(currentDraft);
      setConversationId(id);
      setMainModel(latest?.inference?.settings.model ?? chat.settings.model);
      openrouter.hydrate(chat.settings);
      setRun(latest);
      openrouter.hydrate(latest?.planner?.settings ?? latest?.inference?.settings);
      setPendingId(latest?.run_id ?? chat.latest_run_id);
      setMessageText("");
      setStale(false);
      const catalog = chat.messages.at(-1)?.catalog_id;
      if (catalog) {
        setPlacementCatalog(catalog);
        sessionStorage.setItem("campaign-planner:catalog", catalog);
      }
      sessionStorage.setItem("campaign-planner:conversation", id);
      sessionStorage.setItem("campaign-planner:model", chat.settings.model);
      if (latest?.run_id) sessionStorage.setItem(runKey, latest.run_id);
      // A failed start's original payload must remain available when restoring that same run.
      const pendingStart = sessionStorage.getItem(pendingStartKey);
      if (navigateToWorkspace && pendingStart) {
        const pending = JSON.parse(pendingStart);
        if ((pending.run_id ?? pending.body?.run_id) !== latest?.run_id) sessionStorage.removeItem(pendingStartKey);
      }
      if (navigateToWorkspace) navigate("/campaign");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not open the conversation.");
    } finally {
      setBusy(false);
    }
  }

  function chooseModel(value: string) {
    openrouter.resetSelection();
    newConversation(value, true);
  }
  async function startPlacement(request: string, catalogId: string, permission: DraftPermission) {
    sessionStorage.setItem("campaign-planner:conversation", conversationId);
    navigate("/campaign");
    const pending = sessionStorage.getItem(pendingStartKey);
    if (pending) {
      const saved = JSON.parse(pending);
      if (saved.provider) return prepare();
      if (saved.path === "/api/agent/placements" && saved.body.session_id === conversationId
          && saved.body.request === request && saved.body.catalog_id === catalogId && saved.body.model === mainModel
          && (saved.body.draft_permission ?? "none") === permission) {
        return prepare();
      }
    }
    return prepare({kind: "placement_request", request, model: mainModel, sessionId: conversationId, catalogId,
                    afterMessage: conversation?.latest_message ?? 0, draftPermission: permission});
  }
  const remoteModel = !["simulated", "simulated-inspect", ""].includes(mainModel);
  const inheritedModel = remoteModel
    ? {mode: "openrouter" as const, model: mainModel, budget: account.selection?.max_run_cost_usd} : {mode: "offline" as const};
  const capabilityScope = JSON.stringify([mode?.previewScope, mode?.workspace?.actor, mode?.workspace?.client_id,
    mode?.workspace?.brand_id, mode?.workspace?.id, draft?.campaign_id]);
  const providerAvailable = Boolean(mode?.openrouterAvailable);
  const composer = mode?.agentPlanner && draft && <AgentComposer preview={Boolean(mode.previewScope)} capabilityScope={capabilityScope} options={mode.agentPlanner} model={mainModel}
    providerSelection={account.selection} providerConnected={openrouter.canUse(account.selection ?? undefined)} providerAvailable={providerAvailable}
    catalogId={placementCatalog} onCatalogId={id => {setPlacementCatalog(id); sessionStorage.setItem("campaign-planner:catalog", id);}}
    followup={Boolean(conversation?.messages.length)} text={messageText} onText={setMessageText}
    draftPermission={draftPermission} onDraftPermission={setDraftPermission}
    onModel={chooseModel} onSubmit={startPlacement} busy={busy || !!packageAction} request={request}
    onCatalogs={catalogs => setMode(current => current?.agentPlanner
      ? {...current, agentPlanner: {...current.agentPlanner, catalogs}} : current)} />;
  const result = review(run);
  const waiting = run?.status === "waiting_for_evidence";
  const reviewingTest = run?.request === "Review the original and revised instruction test.";
  const draftApproved = activePackage && !needsLatest ? Boolean(activePackage.approval) : undefined;
  const failureStatus = activityFailureStatus(busy, run?.diagnostics?.status, runFailure?.code);
  const runStatus = failureStatus ?? (result?.needs_verification ? "Earlier reply needs verification"
    : run?.status === "superseded" ? "Request superseded by a follow-up"
    : run?.status === "answered" ? "Reply saved"
    : run?.status === "needs_input" ? "Agent needs input"
    : waiting ? "Waiting for more evidence"
    : result ? (reviewingTest ? "Test assessment saved"
      : result.revision === draftRevision && !needsLatest ? (draftApproved === undefined ? "Draft saved" : draftApproved ? "Draft approved" : "Draft ready for review")
      : `Prepared revision ${result.revision}`)
    : busy || run?.status === "running" ? "Preparing the campaign"
    : pendingId && !stale ? "Preparation can be resumed" : "Waiting for a request");
  const evidenceMessage = conversation?.messages.find(message =>
    message.run_id === run?.run_id && (message.review || message.experiment_review));
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
      <a className="skip-link" href="#workspace-main">Skip to workspace</a>
      <aside className="rail">
        <a className="brand-identity" href="/" onClick={event => follow(event, "/")} aria-label="DG Creative Lab by Dessi Georgieva">
          <img src="/brand/mark.svg" alt="" width="44" height="44" />
          <span className="brand-name">DG Creative Lab<small>By Dessi Georgieva</small></span>
        </a>
        <nav aria-label="Workspace">
          <span className="rail-label">Workspace</span>
          <a className="new-request" href="/?new=1" onClick={event => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            if (!busy && !packageAction) {newConversation(); navigate("/");}
          }}
             aria-current={home ? "page" : undefined}><svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg> New request</a>
          <a href="/campaign" onClick={event => follow(event, "/campaign")}
             aria-current={!home ? "page" : undefined}><svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m3 7 9-4 9 4-9 4ZM3 12l9 4 9-4M3 17l9 4 9-4" /></svg>Campaign</a>
          {!mode?.workspace && !mode?.liveInference && <a href="/placements"><svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="1" /><path d="m10 9 5 3-5 3Z" /></svg>Placements <span aria-hidden="true">↗</span></a>}
        </nav>
        {conversations.length > 0 && <label className="saved-conversations">Saved conversations
          <select aria-label="Saved conversations" value={conversation?.id ?? ""} disabled={busy || !!packageAction}
            onChange={event => {if (event.target.value) void openConversation(event.target.value);}}>
            <option value="">Choose a conversation</option>
            {conversations.map(chat => <option key={chat.id} value={chat.id}>{chat.title}</option>)}
          </select>
        </label>}
        <div className="rail-footer">
          <div className="rail-environment"><span className="rail-label">{mode?.previewScope ? "Protected preview" : mode?.workspace ? "Staff access fixture" : mode?.live ? "Live catalog" : "Local workspace"}</span>
            <p>{mode?.googleAdsReporting ? "Google Ads reporting enabled. Check each report's coverage."
              : mode?.live ? "Check source labels when reviewing evidence." : mode?.previewScope ? "Activity stays in this invite." : "Authored delivery fixtures. Local viewer activity."}</p>
          </div>
          {mode && <WorkspaceAccount name={mode.previewScope ? "Demo reviewer" : mode.workspace?.actor ?? "Local operator"}
            initials={mode.previewScope ? "DP" : mode.workspace ? "SF" : "LO"}
            workspace={mode.workspace ? `${mode.workspace.client_id} · ${mode.workspace.brand_id}` : mode.previewScope ? "Invite workspace" : "Trusted local workspace"}
            preview={Boolean(mode.previewScope)} providerAvailable={providerAvailable} providerReady={Boolean(draft)}
            selectionBusy={busy || Boolean(packageAction)} onModelSettings={() => newConversation(mainModel, true)}
            onModelSelect={selection => newConversation(selection.model, true)}
            onProviderChange={fresh => {viewEpoch.current++; if (fresh) newConversation(mainModel, true);}} />}
        </div>
      </aside>
      <main id="workspace-main" tabIndex={-1}>
        <div className="topline">
          <span>Workspace <span className="crumb-separator" aria-hidden="true">›</span> {home ? "New request" : "Campaign"}</span>
          {mode && <span className="mode">{mode.previewScope ? "Protected demo" : mode.workspace ? "Offline access fixture" : mode.live ? "Live catalog" : mode.googleAdsReporting ? "Local workspace" : "Local demo"}</span>}
        </div>
        {home ? (
          <div className="home">
            <section className="intake" aria-labelledby="page-heading">
              <h1 id="page-heading" tabIndex={-1}>What would you like to prepare?</h1>
              <p className="intake-intro">Describe the campaign task. Your agent chooses tools and prepares a draft for review.</p>
              {composer}
              {error && mode && <p className="error" role="alert">{error}</p>}
              {mode && !mode.live && !mode.liveInference && (
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
                  <CampaignChat conversation={conversation} busy={busy} draftRevision={needsLatest ? undefined : draftRevision} />
                  {composer}
                  {mode && !mode.live && !mode.liveInference && pendingId && !result && <button onClick={() => void prepare()} disabled={busy || !!packageAction}>{action}</button>}
                  {waiting && <p role="status" className="revision">Waiting for more evidence. {result?.message}</p>}
                  {Boolean(run?.steps.length) && <a className="compact-activity" href="#activity-heading">View agent activity</a>}
                  {!mode && !error && <p role="status">Loading the workspace…</p>}
                  {error && <p className="error" role="alert">{error}</p>}
                </section>
                <section aria-labelledby="draft-heading" className="draft">
                  <span className="label">02 / Review</span>
                  <h2 id="draft-heading" tabIndex={-1}>Campaign draft</h2>
                  {draft && <p className="revision">Revision {draft.revision} · {draft.placements.length} placements</p>}
                  {draft && activePackage && !needsLatest && <BriefLearning<Draft>
                    key={`brief:${activePackage.fingerprint}:${deliveryRefresh}:${reviewRefresh}`}
                    campaignId={draft.campaign_id} revision={draft.revision} fingerprint={activePackage.fingerprint}
                    reviewFinding={!draft.instruction_test && activePackage.package.groups.length === 1}
                    applied={draft.instruction_reuse} disabled={busy || !!packageAction}
                    request={request} onDraft={setDraft} onReload={() => void loadLatest()} />}
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
                    const viewerPath = mode?.workspace
                      ? activePackage?.public_comparisons?.find(link => link.creative_ref === example?.creative)?.url
                      : group?.viewer_path ?? (example && "/viewer?ad=" + encodeURIComponent(example.creative));
                    const previewPath = mode?.previewScope
                      ? group?.preview_path?.replace("/viewer/media/", `/viewer/media/${mode.previewScope}/`)
                      : group?.preview_path;
                    return (
                      <section className="context" key={key} aria-label={context.title}>
                        <div className="context-heading">
                          <h3>{context.title}</h3>
                          {mode && viewerPath && <a href={mode.viewerOrigin + viewerPath}>
                            Open comparison <span aria-hidden="true">↗</span>
                          </a>}
                        </div>
                        {mode && previewPath && <a className="creative-preview" href={mode.viewerOrigin + previewPath}
                            target="_blank" rel="noreferrer">Preview {group?.creative_version} ↗</a>}
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
                  {draft && !mode?.workspace && !mode?.liveInference && <a className="text-action" href="/placements">Manage placements and export URLs <span aria-hidden="true">↗</span></a>}
                </section>
                {!mode?.liveInference && activePackage?.approval && !needsLatest && !busy && (
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
                    viewerOrigin={mode.publicViewerOrigin ?? mode.viewerOrigin} googleAds={Boolean(mode.googleAdsReporting)}
                    revision={activePackage.package.revision} fingerprint={activePackage.fingerprint} request={request}
                    onPackageConflict={message => {
                      setPackageChanged(true);
                      setPackageError(message);
                    }} />
                )}
                {!mode?.liveInference && activePackage?.approval && !needsLatest && !busy && (
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
                    viewerOrigin={mode.viewerOrigin} limits={mode.instructionTestLimits} request={request}
                    mainModel={inheritedModel}
                    onPrepareNextTest={(testId, reviewId, selection) => void prepare({kind: "experiment_next_test", testId, reviewId, selection})}
                    onReview={(testId, selection) => void prepare({kind: "instruction_review", testId, selection})}
                    onPackageConflict={message => {
                      setPackageChanged(true);
                      setPackageError(message);
                    }} />
                )}
              </div>
              <AgentActivity run={run} result={result} status={runStatus} draftRevision={needsLatest ? undefined : draftRevision} draftApproved={draftApproved}
                evidenceMessageId={evidenceMessage?.id}
                deliveryRevision={mode && activePackage?.approval && !needsLatest && !busy ? draftRevision : undefined} />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
