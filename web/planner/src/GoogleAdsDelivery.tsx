import {useEffect, useState} from "react";

type Coverage = "complete" | "partial" | "empty" | "unavailable";
type Metrics = {impressions: number; clicks: number; cost_micros: number};
type Report = {
  source: string;
  grain: string;
  placement_grain: string;
  window: {start: string; end: string};
  captured_at: string;
  currency: string;
  coverage: Coverage;
  placement_coverage: Coverage;
  has_delivery: boolean;
  groups: {name: string; ad_group_id: string; configured_videos: string[]; metrics: Metrics | null}[];
  placements: {ad_group_id: string; placement: string; kind: "video" | "other"; metrics: Metrics}[];
};
type DeliveryState = {available: boolean; report: Report | null};
type Props = {
  campaignId: string;
  revision: number;
  fingerprint: string;
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

export function GoogleAdsDelivery({campaignId, revision, fingerprint, request, onPackageConflict}: Props) {
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
      setState({available: true, report});
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
  return (
    <section className="performance" aria-labelledby="google-ads-delivery">
      <h2 id="google-ads-delivery">Google Ads delivery</h2>
      <p className="revision">Read-only reporting for the verified Google Ads test campaign.</p>
      <p className="revision">You can also ask in chat, “Review Google Ads delivery.”</p>
      {state?.available === false && <p>Verify a Google Ads setup for this package to review its delivery.</p>}
      <button onClick={refresh} disabled={!state?.available || busy}>{busy ? "Reviewing…" : "Review Google Ads delivery"}</button>
      {error && <p className="performance-error" role="alert">{error}</p>}
      {report && (
        <div aria-live="polite">
          <p className="revision">{report.source} · {report.window.start} to {report.window.end} · Retrieved {new Date(report.captured_at).toLocaleString()}</p>
          <p>{report.grain} delivery · {coverageText[report.coverage]}</p>
          {report.coverage === "empty" && report.has_delivery === false && <p>No delivery data is available for this test campaign.</p>}
          {report.coverage === "complete" && report.has_delivery === false && <p>Google Ads reports zero delivery for both ad groups.</p>}
          <dl className="setup-details">
            {report.groups.map(group => <div key={group.ad_group_id}>
              <dt>{group.name}</dt>
              <dd>{group.metrics ? metricText(group.metrics, report.currency) : "Delivery metrics unavailable"}</dd>
              <dd>Configured video targets · {group.configured_videos.join(", ")}</dd>
            </div>)}
          </dl>
          <h3>Reported placements</h3>
          <p className="revision">{report.placement_grain} · {coverageText[report.placement_coverage]}</p>
          {report.placements.length > 0 && <ul>
            {report.placements.map(row => <li key={`${row.ad_group_id}:${row.placement}`}>
              {report.groups.find(group => group.ad_group_id === row.ad_group_id)?.name} · {row.kind === "other" ? "Other (aggregated)" : row.placement} · {metricText(row.metrics, report.currency)}
            </li>)}
          </ul>}
        </div>
      )}
    </section>
  );
}
