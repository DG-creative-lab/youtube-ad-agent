import {useEffect, useState} from "react";

type Coverage = "complete" | "partial" | "empty" | "unavailable";
type Metrics = {impressions: number; clicks: number; cost_micros: number};
type Group = {
  name: string;
  ad_group_id: string;
  configured_videos: string[];
  viewer_link: {path: string; destination: string} | null;
};
type Activity = {arrivals: number; completions: number};
type ReviewedGroup = Group & {
  metrics: Metrics | null;
  viewer_activity?: Activity | null;
  window_activity?: (Activity & {rehearsal_arrivals: number; rehearsal_completions: number}) | null;
};
type Recommendation = {
  title: string; reason: string; change?: string; hold_constant?: string; measure?: string;
  correction?: {label: string}; needs_refresh?: boolean;
};
type Report = {
  id: string;
  source: string;
  grain: string;
  placement_grain: string;
  window: {start: string; end: string; time_zone?: string | null} | null;
  captured_at: string;
  currency: string | null;
  coverage: Coverage;
  placement_coverage: Coverage;
  has_delivery: boolean;
  groups: ReviewedGroup[];
  placements: {ad_group_id: string; placement: string; kind: "video" | "other"; metrics: Metrics}[];
};
type DeliveryState = {available: boolean; groups: Group[]; report: Report | null; recommendation: Recommendation | null};
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
  const query = `${path}?revision=${revision}&fingerprint=${fingerprint}`;

  useEffect(() => {
    let current = true;
    request<DeliveryState>(query)
      .then(value => {if (current) setState(value);})
      .catch(failure => {if (current) setError(failure.message);});
    return () => {current = false;};
  }, [request, query]);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const report = await request<Report>(path, {campaign_id: campaignId, revision, fingerprint});
      setState(current => current && {...current, report, recommendation: null});
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

  async function recommend() {
    if (!state?.report) return;
    setBusy(true);
    setError("");
    try {
      const recommendation = await request<Recommendation>(path + "/recommend", {
        campaign_id: campaignId, revision, fingerprint, report_id: state.report.id,
      });
      setState(current => current && {...current, recommendation});
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not recommend a next test.");
      if (failure instanceof Error && "status" in failure && failure.status === 409) {
        const latest = await request<DeliveryState>(query).catch(() => null);
        if (latest) setState(latest);
      }
    } finally {
      setBusy(false);
    }
  }

  const report = state?.report;
  const recommendation = state?.recommendation;
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
          <p className="revision">{report.source}{report.window && ` · ${report.window.start} to ${report.window.end} · ${report.window.time_zone ?? "Account time zone unavailable"}`} · Retrieved {new Date(report.captured_at).toLocaleString()}</p>
          {report.window && <p>{report.grain} delivery · {coverageText[report.coverage]}</p>}
          {report.coverage === "empty" && report.has_delivery === false && <p>No delivery data is available for this test campaign.</p>}
          {report.coverage === "complete" && report.has_delivery === false && <p>Google Ads reports zero delivery for both ad groups.</p>}
        </div>
      )}
      {state?.groups.some(group => group.viewer_link) && <p className="revision">
        All-time counts include rehearsals. Same-window eligible visits exclude marked rehearsals and visits without timestamps.
      </p>}
      {state?.available && <dl className="setup-details" aria-live="polite">
        {state.groups.map(group => {
          const reviewed = report?.groups.find(row => row.ad_group_id === group.ad_group_id);
          const activity = reviewed?.viewer_activity;
          const windowActivity = reviewed?.window_activity;
          const link = group.viewer_link;
          return <div key={group.ad_group_id}>
            <dt>{group.name}</dt>
            <dd>{reviewed?.metrics && report?.currency ? metricText(reviewed.metrics, report.currency)
              : googleAds ? (report ? "Google Ads delivery metrics unavailable" : "Review to load Google Ads delivery")
              : "Google Ads delivery unavailable for simulated setup"}</dd>
            <dd>Configured video targets · {group.configured_videos.join(", ")}</dd>
            {link && <dd><a className="text-action" href={(googleAds ? link.destination : viewerOrigin + link.path) + "&rehearsal=1"}
              aria-label={`Rehearse tagged comparison for ${group.name}`} target="_blank" rel="noreferrer">
              Rehearse tagged comparison <span aria-hidden="true">↗</span></a></dd>}
            <dd>{activity ? `All-time viewer link · Arrivals ${activity.arrivals} · Completions ${activity.completions}`
              : link ? "Review to capture tagged viewer activity" : "Tagged viewer destination unavailable"}</dd>
            {windowActivity && <>
              <dd>Same-window eligible visits · Arrivals {windowActivity.arrivals} · Completions {windowActivity.completions}</dd>
              <dd>Same-window rehearsals · Arrivals {windowActivity.rehearsal_arrivals} · Completions {windowActivity.rehearsal_completions}</dd>
            </>}
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
      {report && <section aria-labelledby="delivery-next-test">
        <h3 id="delivery-next-test">Next test</h3>
        <p className="revision">Uses saved review {report.id.slice(0, 8)}. In chat, ask “Recommend the next test from the saved delivery review.”</p>
        <button onClick={recommend} disabled={busy}>Recommend next test</button>
        {recommendation && <div aria-live="polite">
          {recommendation.needs_refresh && <p>Saved recommendation · Buyer correction changed. Recommend again to apply it.</p>}
          <p><strong>{recommendation.title}</strong></p>
          <p>{recommendation.reason}</p>
          {recommendation.change && <p>{recommendation.change}</p>}
          {recommendation.hold_constant && <p>{recommendation.hold_constant}</p>}
          {recommendation.measure && <p>{recommendation.measure}</p>}
          {recommendation.correction && <p className="revision">Buyer correction · {recommendation.correction.label}</p>}
        </div>}
      </section>}
    </section>
  );
}
