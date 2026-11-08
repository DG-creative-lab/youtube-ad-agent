import {useState} from "react";

export type PlannerOptions = {
  models: {id: string; label: string; mode: string}[];
  default: string;
  catalogs: {id: string; label: string; count: number}[];
  specialist_label: string;
};
type Props = {
  options: PlannerOptions;
  model: string;
  onModel: (model: string) => void;
  onSubmit: (request: string, catalog: string) => void;
  onCatalogs: (catalogs: PlannerOptions["catalogs"]) => void;
  catalogId: string;
  onCatalogId: (id: string) => void;
  busy: boolean;
  request: <T>(path: string, body?: Record<string, unknown>) => Promise<T>;
};

export function AgentComposer({options, model, onModel, onSubmit, onCatalogs, catalogId, onCatalogId, busy, request}: Props) {
  const [text, setText] = useState("Find relevant placements for this Text to Speech campaign.");
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const chosen = catalogId || options.catalogs[0]?.id || "";
  async function importCatalog(file?: File) {
    if (!file) return;
    setError("");
    setImporting(true);
    try {
      if (file.size > 700_000) throw new Error("Use a JSON catalog smaller than 700 KB.");
      const rows: unknown = JSON.parse(await file.text());
      const result = await request<{id: string; catalogs: PlannerOptions["catalogs"]}>("/api/agent/catalog", {label: file.name.slice(0, 100), rows});
      onCatalogs(result.catalogs);
      onCatalogId(result.id);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not import the catalog.");
    } finally {
      setImporting(false);
    }
  }
  return <form className="agent-composer" onSubmit={event => {event.preventDefault(); onSubmit(text, chosen);}}>
    <label>Campaign request
      <textarea value={text} onChange={event => setText(event.target.value)} maxLength={1500} rows={3}
        disabled={busy || importing} required />
    </label>
    <div className="performance-controls">
      <label>Main model
        <select value={model} onChange={event => onModel(event.target.value)} disabled={busy || importing}>
          {options.models.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
        </select>
      </label>
      <label>Catalog
        <select value={chosen} onChange={event => onCatalogId(event.target.value)} disabled={busy || importing}>
          {options.catalogs.map(item => <option key={item.id} value={item.id}>{item.label} · {item.count} videos</option>)}
        </select>
      </label>
      <button disabled={busy || importing || !chosen || !model || !text.trim()}>{busy ? "Preparing…" : "Prepare campaign"}</button>
    </div>
    <p className="revision">{options.specialist_label}. Changing the main model starts a new conversation; existing runs keep their model.</p>
    <details className="catalog-import">
      <summary>Use your own catalog</summary>
      <p className="revision">Import 1–200 independently supplied descriptions with video_id, description, source
        (creator_supplied or licensed), and source_reference. Authored synthetic fixtures are also supported.</p>
      <label>Import JSON catalog<input type="file" accept="application/json,.json" disabled={busy || importing}
        onChange={event => {void importCatalog(event.target.files?.[0]); event.target.value = "";}} /></label>
    </details>
    {importing && <p role="status">Importing catalog…</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </form>;
}
