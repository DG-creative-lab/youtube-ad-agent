/** Foreground credential boundary. Raw keys never leave this module except an allowed HTTP header. */
export type Budget = "0" | "0.25" | "1.00";
export type Selection = {
  selection_id: string; connection_id: string; model: string; profile: "planner" | "structured_review";
  max_run_cost_usd: Budget; catalogue_revision: string; privacy?: unknown; routing?: unknown;
  charging_profile_version?: string; prices?: Record<string, string>;
};
export type Catalogue = {catalogue_revision: string; observed_at: number; expires_at: number;
  models: {id: string; name: string; input_usd_per_million: string | null; output_usd_per_million: string | null;
    state: "candidate" | "eligible" | "blocked"; reason_codes: string[]}[]; next_cursor: string | null};
export type AccountSnapshot = {state: "disconnected" | "reconnect" | "connecting" | "connected" | "expired";
  connectionId: string | null; expiresAt: number | null; selection: Selection | null; epoch: number};
export class RequestError extends Error {
  constructor(message: string, readonly status: number, readonly code = "", readonly retryable = false) {super(message);}
}
export type RunAttempt = {kind: "offline" | "provider" | "unknown"; phase: "start" | "read" | "advance"; acknowledged: boolean};
/** A rejected unsaved offline start can be discarded; a saved or provider operation cannot. */
export function forgetFailedOfflineRun(error: unknown, attempt: RunAttempt) {
  return error instanceof RequestError && !error.code && attempt.kind === "offline" && !attempt.acknowledged
    && (attempt.phase === "start" && [400, 403, 404, 409].includes(error.status)
      || attempt.phase === "read" && error.status === 404);
}
export const id = () => crypto.randomUUID().replaceAll("-", "");
const prefix = "campaign-openrouter:";
const keyPaths = new Set(["/api/openrouter/connect", "/api/openrouter/models", "/api/openrouter/select",
  "/api/openrouter/reconcile", "/api/agent/placements", "/api/agent/next-test", "/api/agent/instruction-review",
  "/api/agent/experiment-next-test", "/api/agent/run"]);
const messages: Record<string, string> = {
  waiting_for_credentials: "Reconnect the original OpenRouter key, then resume this saved operation.",
  inference_outcome_unknown: "The provider outcome is unknown. This operation will not repeat the completion. Saved history remains available.",
  connection_expired: "This connection has expired. Start a new conversation with a new connection; the saved history remains available.",
  credential_mismatch: "This key does not match the original connection. Reconnect using the original key or replace the connection for new work.",
  selection_stale: "The selected route changed. Refresh the model catalogue and choose again for a new conversation.",
  route_unqualified: "This route is not qualified for this request. Choose an eligible model for a new conversation.",
  budget_exhausted: "The operation's budget or shared allowance is exhausted. Its original settings and history are retained.",
  admission_busy: "Another foreground request is busy. Wait, then explicitly resume the same operation.",
  catalogue_unavailable: "The model catalogue is unavailable. Retry the catalogue or use an offline model.",
  authority_unavailable: "Workspace access is temporarily unavailable. No automatic retry was made.",
  access_denied: "Workspace access was denied. Sign in with the appropriate campaign access.",
  sign_in_required: "Sign in again to use this workspace.",
  operation_conflict: "This operation has different saved inputs. Open its saved history before starting new work.",
  invalid_request: "This request was not accepted. Check the connection and selected settings.",
};

export class OpenRouterSession {
  #key: string | null = null;
  #csrf = "";
  #identity: string | null = null;
  #scope: string | null = null;
  #timer: ReturnType<typeof setTimeout> | undefined;
  #listeners = new Set<() => void>();
  #query = 0;
  #selectionEpoch = 0;
  #snapshot: AccountSnapshot;
  readonly tabId: string;
  constructor(private storage: Storage, private fetcher: typeof fetch = fetch.bind(globalThis)) {
    this.tabId = storage.getItem(prefix + "tab_id") ?? id();
    storage.setItem(prefix + "tab_id", this.tabId);
    const connectionId = storage.getItem(prefix + "connection_id");
    this.#snapshot = {state: connectionId ? "reconnect" : "disconnected", connectionId, expiresAt: null, selection: null, epoch: 0};
  }
  snapshot = () => this.#snapshot;
  subscribe = (listener: () => void) => {this.#listeners.add(listener); return () => {this.#listeners.delete(listener);};};
  #publish(change: Partial<AccountSnapshot>) {this.#snapshot = {...this.#snapshot, ...change}; this.#listeners.forEach(listener => listener());}
  #invalidate(state: AccountSnapshot["state"], forget = false) {
    this.#key = null;
    clearTimeout(this.#timer);
    this.#query++; this.#selectionEpoch++;
    if (forget) this.storage.removeItem(prefix + "connection_id");
    this.#publish({state, epoch: this.#snapshot.epoch + 1, ...(forget && {connectionId: null, expiresAt: null, selection: null})});
  }
  clear = () => this.#invalidate(this.#snapshot.connectionId ? "reconnect" : "disconnected");
  logout = () => {this.#invalidate("disconnected", true); this.#identity = null; this.#scope = null;};
  bindScope(scope: string) {
    if (this.#scope !== null && this.#scope !== scope) this.logout();
    this.#scope = scope;
  }
  assertCurrent(epoch: number) {if (epoch !== this.#snapshot.epoch) throw new RequestError("The workspace or connection changed. Open the saved history before continuing.", 409, "client_context_changed");}
  #active() {
    if (this.#snapshot.expiresAt !== null && Date.now() >= this.#snapshot.expiresAt * 1000) this.#invalidate("expired");
    if (!this.#key || this.#snapshot.state !== "connected") throw new RequestError(messages.waiting_for_credentials, 409, "waiting_for_credentials");
  }
  assertSafe(data: unknown) {
    if (!this.#key) return;
    const queue: [unknown, number, number][] = [[data, 0, 0]];
    let count = 0, characters = 0;
    while (queue.length) {
      const [value, depth, decodings] = queue.pop()!;
      if (++count > 100000 || depth > 64) throw new RequestError("The content exceeds the safe inspection limit.", 400, "invalid_request");
      if (typeof value === "string") {
        characters += value.length;
        if (characters > 8000000) throw new RequestError("The content exceeds the safe inspection limit.", 400, "invalid_request");
        if (value.includes(this.#key)) throw new RequestError("Keep the provider key only in the account field. This content was not sent or saved.", 400, "credential_in_content");
        if (/^[\s]*[\[{"]/.test(value)) {
          let decoded: unknown;
          try {decoded = JSON.parse(value);} catch {continue;}
          if (decoded !== value) {
            if (decodings >= 8) throw new RequestError("The content exceeds the safe inspection limit.", 400, "invalid_request");
            queue.push([decoded, depth + 1, decodings + 1]);
          }
        }
      } else if (value && typeof value === "object") {
        if (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype && Object.getPrototypeOf(value) !== null) throw new RequestError("Use plain command data.", 400, "invalid_request");
        for (const [key, item] of Object.entries(value)) queue.push([key, depth + 1, decodings], [item, depth + 1, decodings]);
      } else if (value !== null && value !== undefined && !["number", "boolean"].includes(typeof value)) throw new RequestError("Use plain command data.", 400, "invalid_request");
    }
  }
  serializeStart(start: {path: string; body: Record<string, unknown>}) {
    this.assertSafe(start.body);
    return JSON.stringify(start.body.provider_selection_id
      ? {provider: true, path: start.path, operation_id: start.body.operation_id ?? start.body.run_id,
         ...(start.body.run_id ? {run_id: start.body.run_id} : {})}
      : start);
  }
  #assertCredentialMetadata() {
    if (this.storage.getItem(prefix + "tab_id") !== this.tabId
      || this.storage.getItem(prefix + "connection_id") !== this.#snapshot.connectionId) {
      this.logout();
      throw new RequestError("This tab's connection metadata changed or was cleared. Reload the workspace before connecting again.", 409, "client_context_changed");
    }
  }
  async request<T>(path: string, body?: Record<string, unknown>, credential = false): Promise<T> {
    if (path === "/api/session/end" && body) {
      // Check the known secret before clearing it, even when logout input itself is rejected.
      try {this.assertSafe(body);} finally {this.logout();}
    }
    const proof = this.storage.getItem("placement-review:operator") ?? "";
    if (this.#identity !== null && this.#identity !== proof) this.logout();
    this.#identity = proof;
    const epoch = this.#snapshot.epoch;
    if (credential && location.protocol !== "https:" && !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname)) throw new RequestError("OpenRouter credentials require HTTPS outside the loopback demo.", 400, "invalid_request");
    if (credential && (!body || !keyPaths.has(path))) throw new RequestError("Credential transport is not allowed for this command.", 400, "invalid_request");
    if (credential) this.#assertCredentialMetadata();
    if (credential && path !== "/api/openrouter/connect") this.#active();
    this.assertSafe(body);
    let response: Response;
    try {response = await this.fetcher(path, {method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin",
      headers: {"X-Local-Operator": proof, "X-Placement-Review": "campaign", ...(this.#csrf && {"X-CSRF-Token": this.#csrf}),
        ...(body && {"Content-Type": "application/json"}), ...(credential && this.#key && {"X-OpenRouter-Key": this.#key})},
      body: body ? JSON.stringify(body) : undefined});}
    catch {throw new RequestError("The request outcome is unavailable. No automatic retry was made; open saved history before continuing.", 503, "request_outcome_unavailable");}
    if (credential) {this.assertCurrent(epoch); this.#assertCredentialMetadata();}
    this.#csrf = response.headers.get("X-CSRF-Token") ?? this.#csrf;
    let result: any;
    try {result = await response.json(); this.assertSafe(result); if (!result || typeof result !== "object") throw new Error();}
    catch {throw new RequestError("The response could not be read safely. No automatic retry was made; open saved history before continuing.", 503, "request_outcome_unavailable");}
    if (credential) {this.assertCurrent(epoch); this.#assertCredentialMetadata();}
    if (!response.ok) {
      const code = typeof result.code === "string" ? result.code : "";
      if ([401, 403].includes(response.status) || ["credential_mismatch", "connection_expired", "sign_in_required", "access_denied"].includes(code)) {
        this.#invalidate(code === "connection_expired" ? "expired" : this.#snapshot.connectionId ? "reconnect" : "disconnected");
      }
      throw new RequestError(messages[code] ?? ((credential || code || (path.startsWith("/api/openrouter/") || path.startsWith("/api/agent/"))) ? "The foreground request failed. No automatic retry was made." : result.error ?? "Request failed."), response.status, code, result.retryable === true);
    }
    return result;
  }
  // Read and empty the uncontrolled input before validation or the first await, including replacement failures.
  connect(input: HTMLInputElement, replace = false): Promise<void> {
    const consumed = input.value; input.value = "";
    const old = this.#snapshot.connectionId;
    this.#invalidate("connecting", replace);
    this.#key = consumed;
    const valid = this.#key !== null && /^[\x21-\x7e]{1,512}$/.test(this.#key);
    return this.#connectConsumed(valid, old, replace);
  }
  async #connectConsumed(valid: boolean, old: string | null, replace: boolean) {
    const epoch = this.#snapshot.epoch;
    try {
      if (!valid) throw new RequestError("Enter an ASCII OpenRouter key of at most 512 characters, without spaces or newlines.", 400, "invalid_request");
      if (replace && old) {await this.request("/api/openrouter/disconnect", {connection_id: old, tab_id: this.tabId}); this.assertCurrent(epoch);}
      const result = await this.request<{connection_id: string; expires_at: number}>("/api/openrouter/connect",
        {operation_id: id(), tab_id: this.tabId, ...(!replace && old && {resume_connection_id: old})}, true);
      this.assertCurrent(epoch);
      if (!/^[a-f0-9]{64}$/.test(result.connection_id) || !Number.isFinite(result.expires_at) || result.expires_at * 1000 <= Date.now()) throw new RequestError("The connection response is unavailable. Enter the key again to retry.", 503);
      this.storage.setItem(prefix + "connection_id", result.connection_id);
      this.#publish({state: "connected", connectionId: result.connection_id, expiresAt: result.expires_at});
      this.#timer = setTimeout(() => this.#invalidate("expired"), Math.max(0, result.expires_at * 1000 - Date.now()));
    } catch (error) {
      if (epoch === this.#snapshot.epoch) this.#invalidate(old && !replace ? "reconnect" : "disconnected");
      throw error instanceof RequestError ? error : new RequestError("Could not connect OpenRouter. The key was cleared; enter it again to retry.", 503);
    }
  }
  async disconnect() {
    const connection = this.#snapshot.connectionId;
    this.#invalidate("disconnected", true);
    if (connection) await this.request("/api/openrouter/disconnect", {connection_id: connection, tab_id: this.tabId});
  }
  async models(search: string, cursor: string | null = null) {
    const query = ++this.#query; const epoch = this.#snapshot.epoch;
    const result = await this.request<Catalogue>("/api/openrouter/models", {connection_id: this.#snapshot.connectionId,
      tab_id: this.tabId, search: search.slice(0, 100), cursor}, true);
    this.assertCurrent(epoch);
    if (query !== this.#query) throw new RequestError("A newer catalogue request replaced this result.", 409, "client_context_changed");
    if (!Array.isArray(result.models) || result.models.length > 20 || typeof result.catalogue_revision !== "string" || !Number.isFinite(result.observed_at) || !Number.isFinite(result.expires_at)
      || result.models.some(row => !row || typeof row.id !== "string" || typeof row.name !== "string" || !["candidate", "eligible", "blocked"].includes(row.state) || !Array.isArray(row.reason_codes) || row.reason_codes.some(code => typeof code !== "string"))) {
      throw new RequestError("The model catalogue response is unavailable. Refresh the catalogue or use an offline model.", 503, "catalogue_unavailable");
    }
    return result;
  }
  resetSelection() {this.#selectionEpoch++; this.#publish({selection: null});}
  async select(model: string, catalogue: string, budget: Budget, profile: Selection["profile"] = "planner") {
    const operation = ++this.#selectionEpoch; const epoch = this.#snapshot.epoch;
    const result = await this.request<Selection>("/api/openrouter/select", {operation_id: id(), connection_id: this.#snapshot.connectionId,
      tab_id: this.tabId, model_id: model, catalogue_revision: catalogue, profile, max_run_cost_usd: budget}, true);
    this.assertCurrent(epoch);
    if (operation !== this.#selectionEpoch) throw new RequestError("Model settings changed before selection completed.", 409, "client_context_changed");
    if (result.model !== model || result.profile !== profile || result.max_run_cost_usd !== budget || result.connection_id !== this.#snapshot.connectionId) {
      throw new RequestError("The selected settings do not match this request.", 409, "selection_stale");
    }
    if (profile === "planner") {this.storage.setItem(prefix + "display_model", model); this.#publish({selection: result});}
    return result;
  }
  hydrate(settings?: Partial<Selection>) {
    if (settings?.selection_id && settings.connection_id && settings.model && settings.profile && settings.max_run_cost_usd && settings.catalogue_revision) {
      this.#selectionEpoch++; this.#publish({selection: settings as Selection});
    }
  }
  async structured(model: string) {
    const chosen = this.#snapshot.selection;
    this.#active();
    if (!chosen || chosen.model !== model || chosen.connection_id !== this.#snapshot.connectionId) throw new RequestError(messages.waiting_for_credentials, 409, "waiting_for_credentials");
    const catalogue = await this.models(model);
    return this.select(model, catalogue.catalogue_revision, chosen.max_run_cost_usd, "structured_review");
  }
  canUse(settings?: Partial<Selection>) {
    return this.#snapshot.state === "connected" && !!this.#key && !!settings?.connection_id && settings.connection_id === this.#snapshot.connectionId;
  }
}
export const openrouter = new OpenRouterSession(sessionStorage);
export const request = <T>(path: string, body?: Record<string, unknown>, credential = false) => openrouter.request<T>(path, body, credential);
window.addEventListener("pagehide", openrouter.clear);
window.addEventListener("pageshow", event => {if (event.persisted) openrouter.clear();});
