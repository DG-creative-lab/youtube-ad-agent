import {useEffect, useState} from "react";

type Configuration = {
  account_id: string; status: string; title: string; objective: string; budget_micros: number; schedule: string;
  groups: {context: string; title: string; creative_version: string; destination: string; placement_ids: string[]}[];
};
type Setup = {
  id: string;
  status: "validated" | "creating" | "created" | "unknown" | "verified" | "mismatch";
  plan: Configuration;
  approval: {approved_at: string} | null;
  viewer_links?: {id: string}[];
  readback: {campaign_id: string; configuration: Configuration; groups: {
    context: string; ad_group_id: string; ad_id: string;
  }[]} | null;
};
type Props = {
  campaignId: string; revision: number; fingerprint: string;
  request: <T>(path: string, body?: Record<string, unknown>) => Promise<T>;
  onSetupChanged: () => void;
  onPackageConflict: (message: string) => void;
};

const endpoint = "/api/campaign/setup";
const statuses: Record<Setup["status"], string> = {
  validated: "Validated · ready for approval",
  creating: "Creation requested · check read-back",
  created: "Created · read-back pending",
  unknown: "Creation outcome unknown · check read-back",
  verified: "Verified · simulated campaign paused",
  mismatch: "Read-back differs from the approved setup",
};

function ConfigurationDetails({config}: {config: Configuration}) {
  return <>
    <dl className="setup-details">
      <div><dt>Campaign</dt><dd>{config.title}</dd></div>
      <div><dt>Account</dt><dd>{config.account_id}</dd></div>
      <div><dt>Status</dt><dd>{config.status}</dd></div>
      <div><dt>Budget</dt><dd>{config.budget_micros / 1_000_000} · simulated</dd></div>
      <div><dt>Schedule</dt><dd>{config.schedule}</dd></div>
      <div><dt>Objective</dt><dd>{config.objective}</dd></div>
    </dl>
    {config.groups.map(group => <details key={group.context} className="approval-history">
      <summary>{group.title} · {group.placement_ids.length} placements</summary>
      <p className="revision">Creative {group.creative_version}</p>
      <p className="review-reference">Destination {group.destination}</p>
      <ul>{group.placement_ids.map(id => <li className="review-reference" key={id}>{id}</li>)}</ul>
    </details>)}
  </>;
}

export function CampaignSetup({campaignId, revision, fingerprint, request, onSetupChanged, onPackageConflict}: Props) {
  const [setup, setSetup] = useState<Setup | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const query = new URLSearchParams({revision: String(revision), fingerprint}).toString();

  useEffect(() => {
    let cancelled = false;
    request<Setup | null>(endpoint + "?" + query)
      .then(result => {if (!cancelled) setSetup(result);})
      .catch(failure => {if (!cancelled) setError(failure.message);})
      .finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, [query, request]);

  async function run(action: "validate" | "create" | "reconcile" | "reload") {
    if (working) return;
    setWorking(true);
    setError("");
    try {
      if (action === "reload") {
        setSetup(await request<Setup | null>(endpoint + "?" + query));
      } else {
        setSetup(await request<Setup>(endpoint + "/" + action, {
          campaign_id: campaignId, revision, fingerprint,
          ...(action !== "validate" && {setup_id: setup?.id}),
        }));
      }
      onSetupChanged();
    } catch (failure) {
      if (failure instanceof Error && "status" in failure && failure.status === 409) {
        onPackageConflict(failure.message);
      } else {
        setError(failure instanceof Error ? failure.message : "Could not load the campaign setup.");
      }
    } finally {
      setWorking(false);
    }
  }

  return <section className="performance" aria-labelledby="campaign-setup">
    <h2 id="campaign-setup">Campaign setup</h2>
    <p className="revision">Simulated provider · Approved package revision {revision}</p>
    {error && <p className="performance-error" role="alert">{error}</p>}
    {loading ? <p className="revision" role="status">Loading setup…</p> : error ? (
      <button onClick={() => void run("reload")} disabled={working}>Reload setup</button>
    ) : !setup ? (
      <button onClick={() => void run("validate")} disabled={working}>Validate paused setup</button>
    ) : <>
      <p className="revision" role="status">{statuses[setup.status]}</p>
      {setup.status === "verified" && !setup.viewer_links?.length &&
        <p className="revision">This setup predates tagged viewer links. Approve a new package revision to rehearse with tagged destinations.</p>}
      <details className="approval-history" open={setup.status === "validated"}>
        <summary>Validated configuration</summary>
        <ConfigurationDetails config={setup.plan} />
      </details>
      {setup.status === "validated" && <button onClick={() => void run("create")} disabled={working}>
        Approve and create paused campaign
      </button>}
      {["creating", "created", "unknown"].includes(setup.status) && <button onClick={() => void run("reconcile")} disabled={working}>
        Check provider read-back
      </button>}
      {setup.readback && <details className="approval-history" open>
        <summary>Provider read-back · simulated</summary>
        <p className="review-reference">Campaign ID {setup.readback.campaign_id}</p>
        <ConfigurationDetails config={setup.readback.configuration} />
        <ul>{setup.readback.groups.map(group => <li key={group.context} className="review-reference">
          {group.context} · Ad group {group.ad_group_id} · Ad {group.ad_id}
        </li>)}</ul>
      </details>}
    </>}
  </section>;
}
