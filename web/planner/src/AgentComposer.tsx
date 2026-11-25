import {useId, useRef, useState} from "react";
import {openrouter} from "./openrouter-session";
import type {Selection} from "./openrouter-session";
import {AgentCapabilities} from "./AgentCapabilities";

export type DraftPermission = "none" | "placements" | "instruction_test";
export const draftPermissionLabels: Record<DraftPermission, string> = {
  none: "Review only", placements: "Placement draft", instruction_test: "Instruction-test draft",
};

export function modelLabel(model: string) {
  if (model === "simulated") return "Offline demo";
  if (model === "simulated-inspect") return "Offline demo · inspect first";
  return model;
}

export type PlannerOptions = {
  models: {id: string; label: string; mode: string}[];
  default: string;
  catalogs: {id: string; label: string; count: number}[];
};
type Props = {
  preview: boolean;
  capabilityScope: string;
  providerSelection: Selection | null;
  providerConnected: boolean;
  providerAvailable: boolean;
  options: PlannerOptions;
  model: string;
  onModel: (model: string) => void;
  onSubmit: (request: string, catalog: string, draftPermission: DraftPermission) => Promise<boolean>;
  onCatalogs: (catalogs: PlannerOptions["catalogs"]) => void;
  catalogId: string;
  onCatalogId: (id: string) => void;
  busy: boolean;
  followup: boolean;
  text: string;
  onText: (text: string) => void;
  draftPermission: DraftPermission;
  onDraftPermission: (permission: DraftPermission) => void;
  request: <T>(path: string, body?: Record<string, unknown>) => Promise<T>;
};

export function AgentComposer({preview, options, model, onModel, onSubmit, onCatalogs, catalogId, onCatalogId, busy, followup, text, onText,
  draftPermission, onDraftPermission, request, capabilityScope, providerSelection, providerConnected, providerAvailable}: Props) {
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [panel, setPanel] = useState<"model" | "catalog" | "import" | "permission" | "capabilities" | null>(null);
  const panelId = useId();
  const modelButton = useRef<HTMLButtonElement>(null);
  const capabilityButton = useRef<HTMLButtonElement>(null);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  const chosen = catalogId || options.catalogs[0]?.id || "";
  const remote = !["simulated", "simulated-inspect", ""].includes(model);
  const selectedModel = options.models.find(item => item.id === model) ?? (remote ? {id: model, label: model, mode: "openrouter"} : undefined);
  const modelChoices = preview ? options.models.filter(item => item.id === "simulated") : options.models;
  const displayModel = !model ? "Choose model" : remote ? selectedModel?.label ?? model : modelLabel(model);
  const providerReady = !remote || providerAvailable && providerConnected && providerSelection?.model === model;
  const selectedCatalog = options.catalogs.find(item => item.id === chosen);
  const disabled = busy || importing;
  async function importCatalog(file?: File) {
    if (!file) return;
    setError("");
    setImporting(true);
    try {
      if (file.size > 700_000) throw new Error("Use a JSON catalog smaller than 700 KB.");
      const contents = await file.text();
      openrouter.assertSafe(contents);
      const rows: unknown = JSON.parse(contents);
      const result = await request<{id: string; catalogs: PlannerOptions["catalogs"]}>("/api/agent/catalog", {label: file.name.slice(0, 100), rows});
      onCatalogs(result.catalogs);
      onCatalogId(result.id);
      setPanel(null);
    } catch (failure) {
      setError(failure instanceof SyntaxError ? "Could not import the catalog. Use valid JSON with permitted video descriptions." : failure instanceof Error ? failure.message : "Could not import the catalog.");
    } finally {
      setImporting(false);
    }
  }
  return <form className="agent-composer" onKeyDown={event => {
    if (event.key === "Escape" && panel) {
      const trigger = panel === "capabilities" ? capabilityButton : modelButton;
      setPanel(null); trigger.current?.focus();
    }
  }} onBlur={event => {
    if (panel === "model" && !event.currentTarget.contains(event.relatedTarget)) setPanel(null);
  }} onSubmit={event => {
    event.preventDefault();
    void onSubmit(text, chosen, draftPermission).then(sent => {if (sent) {onText(""); onDraftPermission("none");}});
  }}>
    <div className="composer-input">
      <label className="sr-only" htmlFor={`${panelId}-message`}>{followup ? "Your message" : "Campaign request"}</label>
      <textarea ref={messageInput} id={`${panelId}-message`} value={text} onChange={event => {try {openrouter.assertSafe(event.target.value); onText(event.target.value);} catch {event.target.value = ""; onText(""); setError("Keep the provider key only in the account field. This content was not saved.");}}} maxLength={1500} rows={3}
        placeholder={followup ? "Answer the agent or refine this campaign…" : "Describe what you would like to prepare…"}
        disabled={disabled} required />
      <div className="composer-toolbar">
        <div className="composer-actions">
          {providerAvailable ? <span className="composer-current-model">{model ? displayModel : "Set up OpenRouter in your account"}</span> : <button ref={modelButton} type="button" className="model-trigger" aria-label={`Model: ${displayModel}`}
            aria-expanded={panel === "model"} aria-controls={`${panelId}-models`} disabled={disabled}
            onClick={() => setPanel(panel === "model" ? null : "model")}>
            <span className="model-caption" aria-hidden="true">Model</span>
            <span className="model-value">{displayModel}</span><span aria-hidden="true">⌄</span>
          </button>}
          <button className="composer-send" aria-label={busy ? "Working" : followup ? "Send follow-up" : "Send request"}
            title={followup ? "Send follow-up" : "Send request"}
            disabled={disabled || !chosen || !model || !text.trim() || !selectedModel || !providerReady}>
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M12 19V5m-6 6 6-6 6 6" />
            </svg>
          </button>
        </div>
      </div>
      {panel === "model" && <div id={`${panelId}-models`} className="model-menu" role="group" aria-label="Model options">
        <span className="label">Model</span>
        {modelChoices.map(item => <label key={item.id} className="model-option">
          <input type="radio" name={`${panelId}-model`} value={item.id} checked={item.id === model} disabled={disabled}
            onChange={() => {onModel(item.id); setPanel(null); modelButton.current?.focus();}} />
          <span><strong>{item.mode === "simulated" ? modelLabel(item.id) : item.label}</strong><small>{item.mode === "openrouter" ? "Live · enabled on this server" : "Offline · authored simulation"}</small></span>
        </label>)}
        <p>Changing the model starts a new conversation in this campaign.</p>
      </div>}
    </div>
    <div className="composer-pills" aria-label="Message options">
      <button type="button" className="composer-pill" disabled={disabled} aria-expanded={panel === "permission"}
        aria-controls={`${panelId}-permission`} onClick={() => setPanel(panel === "permission" ? null : "permission")}>
        Changes · {draftPermissionLabels[draftPermission]}
      </button>
      <button type="button" className="composer-pill" disabled={disabled} aria-expanded={panel === "catalog"}
        aria-controls={`${panelId}-catalog`} onClick={() => setPanel(panel === "catalog" ? null : "catalog")}>
        <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
          <path d="m10 2 8 4-8 4-8-4 8-4Zm-8 8 8 4 8-4M2 14l8 4 8-4" />
        </svg> Catalog <span>{selectedCatalog?.count ?? 0}</span>
      </button>
      {(!preview || providerAvailable) && <button type="button" className="composer-pill" disabled={disabled} aria-expanded={panel === "import"}
        aria-controls={`${panelId}-import`} onClick={() => setPanel(panel === "import" ? null : "import")}>
        <span aria-hidden="true">+</span> Import
      </button>}
      <button ref={capabilityButton} type="button" className="composer-pill" aria-expanded={panel === "capabilities"}
        aria-controls={`${panelId}-capabilities`} onClick={() => setPanel(panel === "capabilities" ? null : "capabilities")}>
        Capabilities
      </button>
      <span className="catalog-caption" title={selectedCatalog?.label}>{selectedCatalog?.label}</span>
    </div>
    {panel === "capabilities" && <section id={`${panelId}-capabilities`} className="composer-panel" aria-label="Agent capabilities">
      <AgentCapabilities key={capabilityScope} scope={capabilityScope} request={request} disabled={disabled}
        onExample={example => {onText(example); setPanel(null); messageInput.current?.focus();}} />
    </section>}
    {panel === "permission" && <section id={`${panelId}-permission`} className="composer-panel" aria-label="Draft permissions">
      <label>Allowed draft changes
        <select value={draftPermission} disabled={disabled}
          onChange={event => onDraftPermission(event.target.value as DraftPermission)}>
          {Object.entries(draftPermissionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <p>Applies only to this request. Review only allows no campaign draft changes. Approval, export and launch are separate actions.</p>
    </section>}
    {panel === "catalog" && <section id={`${panelId}-catalog`} className="composer-panel" aria-label="Catalog options">
      <label>Catalog
        <select value={chosen} onChange={event => onCatalogId(event.target.value)} disabled={disabled}>
          {options.catalogs.map(item => <option key={item.id} value={item.id}>{item.label} · {item.count} videos</option>)}
        </select>
      </label>
      <p>Choose the source videos for this message. Existing placements are preserved.</p>
    </section>}
    {panel === "import" && <section id={`${panelId}-import`} className="composer-panel" aria-label="Import catalog">
      <label>Import JSON catalog<input type="file" accept="application/json,.json" disabled={disabled}
        onChange={event => {void importCatalog(event.target.files?.[0]); event.target.value = "";}} /></label>
      <p>Up to 200 permitted descriptions with video_id, description, source and source_reference. Use creator_supplied, licensed or synthetic sources.</p>
    </section>}
    {providerAvailable && !model && <p className="composer-note">Choose your model and budget in OpenRouter account settings.</p>}
    {remote && !providerReady && <p className="revision" role="status">{providerAvailable ? "Open OpenRouter account settings to reconnect or choose a model for a new conversation." : "This saved model is unavailable here. Choose Offline demo to start a new conversation."}</p>}
    {followup && <p className="composer-note">A follow-up stops any unfinished request in this conversation.</p>}
    {importing && <p role="status">Importing catalog…</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </form>;
}
