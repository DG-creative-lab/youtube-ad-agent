import {useEffect, useRef, useState, useSyncExternalStore} from "react";
import {openrouter} from "./openrouter-session";
import type {Budget, Catalogue, Selection} from "./openrouter-session";

export function OpenRouterModels({onSelect, onSettingsChange}: {onSelect: (selection: Selection) => void; onSettingsChange: () => void}) {
  const account = useSyncExternalStore(openrouter.subscribe, openrouter.snapshot);
  const [search, setSearch] = useState("");
  const [budget, setBudget] = useState<Budget>(account.selection?.max_run_cost_usd ?? "0.25");
  const [catalogue, setCatalogue] = useState<Catalogue>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const loading = useRef(false);
  const searchButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {generation.current++; loading.current = false; setCatalogue(undefined); setError(""); setBusy(false);}, [account.epoch]);
  useEffect(() => () => {generation.current++;}, []);
  async function load(cursor: string | null = null, trigger?: HTMLButtonElement) {
    if (loading.current) return;
    loading.current = true;
    // Pagination removes its own button. Keep focus on a stable control only when this action owned it.
    if (trigger && document.activeElement === trigger) searchButton.current?.focus();
    const current = ++generation.current;
    setBusy(true); setError(""); setCatalogue(undefined);
    try {const rows = await openrouter.models(search, cursor); if (current === generation.current) setCatalogue(rows);}
    catch (failure) {if (current === generation.current) setError(failure instanceof Error ? failure.message : "Could not load models.");}
    finally {if (current === generation.current) {loading.current = false; setBusy(false);}}
  }
  async function choose(model: string, trigger: HTMLButtonElement) {
    if (!catalogue || loading.current) return;
    loading.current = true;
    if (document.activeElement === trigger) searchButton.current?.focus();
    const current = ++generation.current;
    onSettingsChange(); openrouter.resetSelection(); setBusy(true); setError("");
    try {
      const selection = await openrouter.select(model, catalogue.catalogue_revision, budget);
      if (current === generation.current) onSelect(selection);
    } catch (failure) {if (current === generation.current) setError(failure instanceof Error ? failure.message : "Could not select this model.");}
    finally {if (current === generation.current) {loading.current = false; setBusy(false);}}
  }
  return <section className="provider-models" aria-label="OpenRouter models">
    <h3>OpenRouter models</h3>
    {account.state !== "connected" ? <p>Connect OpenRouter from the account menu.</p> : <>
      <label>Per-run local budget (USD)
        <select value={budget} disabled={busy} onChange={event => {
          setBudget(event.target.value as Budget); openrouter.resetSelection(); onSettingsChange();
        }}><option value="0">$0 · free qualified routes</option><option value="0.25">$0.25</option><option value="1.00">$1.00</option></select>
      </label>
      <p className="revision">A local reservation ceiling, not an external billing guarantee. A positive budget cannot qualify a blocked route. Changing settings starts a new conversation with Review only.</p>
      <label>Search model catalogue<input value={search} maxLength={100} onChange={event => {
        generation.current++; loading.current = false; setBusy(false); setCatalogue(undefined); setError(""); setSearch(event.target.value);
      }} onKeyDown={event => {if (event.key === "Enter") {event.preventDefault(); void load();}}} /></label>
      <button ref={searchButton} type="button" aria-disabled={busy} onClick={() => void load()}>{busy ? "Loading…" : "Search models"}</button>
      {error && <p className="error" role="alert">{error}</p>}
      {busy && <p role="status">Checking the current route and prices…</p>}
      {catalogue && <>
        <p className="revision">Observed {new Date(catalogue.observed_at * 1000).toLocaleTimeString()} · Up to 20 results per page. Selection revalidates prices and compatibility.</p>
        {!catalogue.models.length && <p role="status">No models match this search.</p>}
        <ul className="provider-model-list">{catalogue.models.map(model => <li key={model.id}>
          <strong>{model.name}</strong><span className="model-id">{model.id}</span>
          <p>Input ${model.input_usd_per_million ?? "unknown"} / million tokens · Output ${model.output_usd_per_million ?? "unknown"} / million tokens</p>
          <p>{model.state === "eligible" ? "Eligible · current selection checks still apply" : model.state === "candidate" ? "Candidate · route qualification required" : "Blocked"}{model.reason_codes.length > 0 && ` · ${model.reason_codes.join(", ").replaceAll("_", " ")}`}</p>
          <button type="button" disabled={busy || model.state !== "eligible"} onClick={event => void choose(model.id, event.currentTarget)}>Use {model.name}</button>
        </li>)}</ul>
        {catalogue.next_cursor && <button type="button" disabled={busy} onClick={event => void load(catalogue.next_cursor, event.currentTarget)}>Next 20 models</button>}
      </>}
      {account.selection && <p className="revision">Selected {account.selection.model} · ${account.selection.max_run_cost_usd} local ceiling · No-training routing; safety retention may apply. No model fallback.</p>}
    </>}
  </section>;
}
