import {useEffect, useId, useRef, useState, useSyncExternalStore} from "react";
import {openrouter} from "./openrouter-session";
import type {Budget, Catalogue, Selection, ModelSort} from "./openrouter-session";

export function OpenRouterModels({onSelect, onSettingsChange, disabled}: {
  onSelect: (selection: Selection) => void;
  onSettingsChange: () => void;
  disabled: boolean;
}) {
  const filterId = useId();
  const account = useSyncExternalStore(openrouter.subscribe, openrouter.snapshot);
  const [search, setSearch] = useState("");
  const [budget, setBudget] = useState<Budget>(account.selection?.max_run_cost_usd ?? "0.25");
  const [catalogue, setCatalogue] = useState<Catalogue>();
  const [maxInput, setMaxInput] = useState("");
  const [maxOutput, setMaxOutput] = useState("");
  const [sort, setSort] = useState<ModelSort>("available");
  const [dirty, setDirty] = useState(false);
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
  function invalidateFilters() {
    generation.current++; loading.current = false; setBusy(false); setError(""); setDirty(true);
  }
  async function load(cursor: string | null = null, trigger?: HTMLButtonElement) {
    if (loading.current || disabled) return;
    loading.current = true;
    // Pagination removes its own button. Keep focus on a stable control only when this action owned it.
    if (trigger && document.activeElement === trigger) searchButton.current?.focus();
    const current = ++generation.current;
    setBusy(true); setError(""); setDirty(true);
    try {
      const rows = await openrouter.models(search, cursor, {max_input_price: maxInput || null,
        max_output_price: maxOutput || null, sort});
      if (current === generation.current) {setCatalogue(rows); setDirty(false);}
    }
    catch (failure) {if (current === generation.current) setError(failure instanceof Error ? failure.message : "Could not load models.");}
    finally {if (current === generation.current) {loading.current = false; setBusy(false);}}
  }
  async function choose(model: string, trigger: HTMLButtonElement) {
    if (!catalogue || dirty || loading.current || disabled) return;
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
      <label htmlFor={`${filterId}-budget`}>Per-run local budget (USD)</label>
        <select id={`${filterId}-budget`} value={budget} disabled={busy || disabled} onChange={event => {
          setBudget(event.target.value as Budget); openrouter.resetSelection(); onSettingsChange();
        }}><option value="0">$0 · free qualified routes</option><option value="0.25">$0.25</option><option value="1.00">$1.00</option></select>
      <p className="revision">Changing the model or budget starts a new conversation with Review only. Your typed message is retained.</p>
      <p className="revision">Only text models with tool calling and required tool choice are listed. Prices are per million tokens.</p>
      <search>
        <form action="/api/openrouter/models" method="post" aria-label="Filter model catalogue"
          onSubmit={event => {event.preventDefault(); void load();}}>
          <label>Search model catalogue<input name="search" type="search" value={search} maxLength={100}
            autoCapitalize="none" autoCorrect="off" spellCheck={false} enterKeyHint="search" disabled={disabled}
            onChange={event => {invalidateFilters(); setSearch(event.target.value);}} /></label>
          <div className="model-price-filters">
            <label>Max input price ($ / 1M tokens)<input name="max_input_price" type="text" inputMode="decimal"
              pattern="[0-9]{1,12}([.][0-9]{1,18})?" maxLength={31} placeholder="Any" value={maxInput} disabled={disabled}
              onChange={event => {invalidateFilters(); setMaxInput(event.target.value);}} /></label>
            <label>Max output price ($ / 1M tokens)<input name="max_output_price" type="text" inputMode="decimal"
              pattern="[0-9]{1,12}([.][0-9]{1,18})?" maxLength={31} placeholder="Any" value={maxOutput} disabled={disabled}
              onChange={event => {invalidateFilters(); setMaxOutput(event.target.value);}} /></label>
          </div>
          <label htmlFor={`${filterId}-sort`}>Sort models</label><select id={`${filterId}-sort`} name="sort" value={sort} disabled={disabled}
            onChange={event => {invalidateFilters(); setSort(event.target.value as ModelSort);}}>
            <option value="available">Available first</option>
            <option value="pricing-low-to-high">Price · low to high</option>
            <option value="pricing-high-to-low">Price · high to low</option>
            <option value="most-popular">OpenRouter popularity</option>
            <option value="intelligence-high-to-low">Intelligence · Artificial Analysis</option>
          </select>
          <p className="revision">Price ordering uses the average input and output token rate. Intelligence ordering comes from OpenRouter’s Artificial Analysis ranking. Models without a score appear last.</p>
          <button ref={searchButton} type="submit" disabled={disabled} aria-disabled={busy || disabled}>{busy ? "Loading…" : "Apply filters"}</button>
        </form>
      </search>
      <p role="status" className="revision">{busy ? "Loading matching models…" : dirty ? "Apply filters to update the results."
        : catalogue ? `Showing ${catalogue.models.length} models in the selected order.` : ""}</p>
      {error && <p className="error" role="alert">{error}</p>}
      {catalogue && <>
        <p className="revision">Observed {new Date(catalogue.observed_at * 1000).toLocaleTimeString()} · Up to 20 results per page. Selection revalidates prices and compatibility.</p>
        {!dirty && !catalogue.models.length && <p>No tool-use models match these filters. Adjust the search or price limits.</p>}
        <ul className="provider-model-list">{catalogue.models.map(model => <li key={model.id}>
          <strong>{model.name}</strong><span className="model-id">{model.id}</span>
          <p>Input ${model.input_usd_per_million ?? "unknown"} / million tokens · Output ${model.output_usd_per_million ?? "unknown"} / million tokens</p>
          <p>{model.state === "eligible" ? "Available · route and prices checked on selection" : model.state === "candidate" ? "Unavailable · route has not been enabled for this application" : "Unavailable · capabilities or pricing are unsupported"}</p>
          <button type="button" disabled={busy || dirty || disabled || model.state !== "eligible"} onClick={event => void choose(model.id, event.currentTarget)}>Use {model.name}</button>
        </li>)}</ul>
        {catalogue.next_cursor && <button type="button" disabled={busy || dirty || disabled} onClick={event => void load(catalogue.next_cursor, event.currentTarget)}>Next 20 models</button>}
      </>}
      <p className="revision">The budget reserves a local maximum for a run. Set a spending limit on your OpenRouter key as well.</p>
      {account.selection && <p role="status" className="revision">Selected {account.selection.model} · ${account.selection.max_run_cost_usd} local ceiling · No-training routing; safety retention may apply. No model fallback.</p>}
    </>}
  </section>;
}
