import {useEffect, useRef, useState, useSyncExternalStore} from "react";
import {openrouter} from "./openrouter-session";
import type {Budget, Catalogue, Selection} from "./openrouter-session";

export function OpenRouterModels({onSelect, onSettingsChange, disabled}: {
  onSelect: (selection: Selection) => void;
  onSettingsChange: () => void;
  disabled: boolean;
}) {
  const account = useSyncExternalStore(openrouter.subscribe, openrouter.snapshot);
  const [search, setSearch] = useState("");
  const [budget, setBudget] = useState<Budget>(account.selection?.max_run_cost_usd ?? "0.25");
  const [catalogue, setCatalogue] = useState<Catalogue>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const loading = useRef(false);
  const searchButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    generation.current++; loading.current = false; setCatalogue(undefined); setError(""); setBusy(false);
    if (account.state === "connected") void load();
    return () => {generation.current++; loading.current = false;};
  }, [account.epoch, account.state]);
  async function load(cursor: string | null = null, trigger?: HTMLButtonElement) {
    if (loading.current || disabled) return;
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
    if (!catalogue || loading.current || disabled) return;
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
    <h3>Model and budget</h3>
    {account.state !== "connected" ? <p>Connect OpenRouter from the account menu.</p> : <>
      <label>Per-run local budget (USD)
        <select value={budget} disabled={busy || disabled} onChange={event => {
          setBudget(event.target.value as Budget); openrouter.resetSelection(); onSettingsChange();
        }}><option value="0">$0 · free qualified routes</option><option value="0.25">$0.25</option><option value="1.00">$1.00</option></select>
      </label>
      <p className="revision">Changing the model or budget starts a new conversation with Review only. Your typed message is retained.</p>
      <p className="revision">Search uses OpenRouter’s catalogue. Models enabled for this application can be selected after route and price checks.</p>
      <label>Search model catalogue<input value={search} maxLength={100} onChange={event => {
        generation.current++; loading.current = false; setBusy(false); setCatalogue(undefined); setError(""); setSearch(event.target.value);
      }} onKeyDown={event => {if (event.key === "Enter") {event.preventDefault(); void load();}}} /></label>
      <button ref={searchButton} type="button" aria-disabled={busy || disabled} onClick={() => void load()}>{busy ? "Loading…" : "Search models"}</button>
      {error && <p className="error" role="alert">{error}</p>}
      {busy && <p role="status">Checking the current route and prices…</p>}
      {catalogue && <>
        <p className="revision">Observed {new Date(catalogue.observed_at * 1000).toLocaleTimeString()} · Up to 20 results per page. Selection revalidates prices and compatibility.</p>
        {!catalogue.models.length && <p role="status">No models match this search. Try a model name or ID, such as gpt-oss or openai/gpt-4.1-mini.</p>}
        <ul className="provider-model-list">{catalogue.models.map(model => <li key={model.id}>
          <strong>{model.name}</strong><span className="model-id">{model.id}</span>
          <p>Input ${model.input_usd_per_million ?? "unknown"} / million tokens · Output ${model.output_usd_per_million ?? "unknown"} / million tokens</p>
          <p>{model.state === "eligible" ? "Available · route and prices checked on selection" : model.state === "candidate" ? "Unavailable · route has not been enabled for this application" : "Unavailable · capabilities or pricing are unsupported"}</p>
          <button type="button" disabled={busy || disabled || model.state !== "eligible"} onClick={event => void choose(model.id, event.currentTarget)}>Use {model.name}</button>
        </li>)}</ul>
        {catalogue.next_cursor && <button type="button" disabled={busy || disabled} onClick={event => void load(catalogue.next_cursor, event.currentTarget)}>Next 20 models</button>}
      </>}
      <p className="revision">The budget reserves a local maximum for a run. Set a spending limit on your OpenRouter key as well.</p>
      {account.selection && <p role="status" className="revision">Selected {account.selection.model} · ${account.selection.max_run_cost_usd} local ceiling · No-training routing; safety retention may apply. No model fallback.</p>}
    </>}
  </section>;
}
