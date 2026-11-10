import {useEffect, useState} from "react";

type Coverage = "complete" | "partial" | "empty" | "unavailable";
type Metrics = {impressions: number; clicks: number; cost_micros: number};
type Group = {
  name: string;
  ad_group_id: string;
  configured_videos: string[];
  viewer_link: {path: string; destination: string} | null;
};
type ReviewedGroup = Group & {metrics: Metrics | null; viewer_activity?: {arrivals: number; completions: number} | null};
type Report = {
  source: string;
  grain: string;
  placement_grain: string;
  window: {start: string; end: string} | null;
  captured_at: string;
  currency: string | null;
  coverage: Coverage;
  placement_coverage: Coverage;
  has_delivery: boolean;
  groups: ReviewedGroup[];
  placements: {ad_group_id: string; placement: string; kind: "video" | "other"; metrics: Metrics}[];
};
type DeliveryState = {available: boolean; groups: Group[]; report: Report | null};
type Props = {
  campaignId: string;
  revision: number;
  fingerprint: string;
  viewerOrigin: string;
  googleAds: boolean;
  request: <T>(path: string, body?: Record<string, unknown>) => Promise<T>;
  onPackageConflict: (message: string) => void;
};

const path = "/api/campaign/google-ads-delivery";
const coverageText: Record<Coverage, string> = {
  complete: "Complete",
  partial: "Partial",
  empty: "No data returned",
  unavailable: "Unavailable",
};

function metricText(metrics: Metrics, currency: string) {
  const cost = new Intl.NumberFormat("en-GB", {style: "currency", currency}).format(metrics.cost_micros / 1_000_000);
  return `${metrics.impressions.toLocaleString()} impressions · ${metrics.clicks.toLocaleString()} clicks · ${cost}`;
}

export function GoogleAdsDelivery({campaignId, revision, fingerprint, viewerOrigin, googleAds, request, onPackageConflict}: Props) {
  const [state, setState] = useState<DeliveryState>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    request<DeliveryState>(`${path}?revision=${revision}&fingerprint=${fingerprint}`)
      .then(value => {if (current) setState(value);})
      .catch(failure => {if (current) setError(failure.message);});
    return () => {current = false;};
  }, [request, revision, fingerprint]);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const report = await request<Report>(path, {campaign_id: campaignId, revision, fingerprint});
      setState(current => current && {...current, report});
    } catch (failure) {
      if (failure instanceof Error && "status" in failure && failure.status === 409) {
        onPackageConflict(failure.message);
      } else {
        setError(failure instanceof Error ? failure.message : "Could not read Google Ads delivery.");
      }
    } finally {
      setBusy(false);
    }
  }

  const report = state?.report;
  if (!googleAds && !state?.available && !error) return null;
  const command = googleAds ? "Review Google Ads delivery" : "Review ad viewer activity";
  return (
    <section className="performance" aria-labelledby="google-ads-delivery">
      <h2 id="google-ads-delivery">{googleAds ? "Google Ads delivery" : "Ad viewer activity"}</h2>
      <p className="revision">{googleAds ? "Read-only reporting for the verified Google Ads test campaign." : "Offline rehearsal · Simulated setup"}</p>
      <p className="revision">You can also ask in chat, “{command}.”</p>
      {state?.available === false && <p>Verify a Google Ads setup for this package to review its delivery.</p>}
      <button onClick={refresh} disabled={!state?.available || busy}>{busy ? "Reviewing…" : command}</button>
      {error && <p className="performance-error" role="alert">{error}</p>}
      {report && (
        <div aria-live="polite">
          <p className="revision">{report.source}{report.window && ` · ${report.window.start} to ${report.window.end}`} · Retrieved {new Date(report.captured_at).toLocaleString()}</p>
          {report.window && <p>{report.grain} delivery · {coverageText[report.coverage]}</p>}
          {report.coverage === "empty" && report.has_delivery === false && <p>No delivery data is available for this test campaign.</p>}
          {report.coverage === "complete" && report.has_delivery === false && <p>Google Ads reports zero delivery for both ad groups.</p>}
        </div>
      )}
      {state?.groups.some(group => group.viewer_link) && (
        <p className="revision">Viewer arrivals and completions cover all recorded visits through each tagged link, including rehearsals.</p>
      )}
      {state?.available && <dl className="setup-details" aria-live="polite">
        {state.groups.map(group => {
          const reviewed = report?.groups.find(row => row.ad_group_id === group.ad_group_id);
          const activity = reviewed?.viewer_activity;
          const link = group.viewer_link;
          return <div key={group.ad_group_id}>
            <dt>{group.name}</dt>
            <dd>{reviewed?.metrics && report?.currency ? metricText(reviewed.metrics, report.currency)
              : googleAds ? (report ? "Google Ads delivery metrics unavailable" : "Review to load Google Ads delivery")
              : "Google Ads delivery unavailable for simulated setup"}</dd>
            <dd>Configured video targets · {group.configured_videos.join(", ")}</dd>
            {link && <dd><a className="text-action" href={googleAds ? link.destination : viewerOrigin + link.path}
              aria-label={`Open tagged comparison for ${group.name}`} target="_blank" rel="noreferrer">
              Open tagged comparison <span aria-hidden="true">↗</span></a></dd>}
            <dd>{activity ? `Viewer link · Arrivals ${activity.arrivals} · Completions ${activity.completions}`
              : link ? "Review to capture tagged viewer activity" : "Tagged viewer destination unavailable"}</dd>
          </div>;
        })}
      </dl>}
      {report?.window && (
        <div>
          <h3>Reported placements</h3>
          <p className="revision">{report.placement_grain} · {coverageText[report.placement_coverage]}</p>
          {report.placements.length > 0 && <ul>
            {report.placements.map(row => <li key={`${row.ad_group_id}:${row.placement}`}>
              {report.groups.find(group => group.ad_group_id === row.ad_group_id)?.name} · {row.kind === "other" ? "Other (aggregated)" : row.placement} · {report.currency && metricText(row.metrics, report.currency)}
            </li>)}
          </ul>}
        </div>
      )}
    </section>
  );
}
