import {useEffect, useRef} from "react";

type ReviewEvidence = {
  id: string; revision: number;
  sample_delivery: {label: string; source: string; coverage: string; rows: {
    creative_version: string; metrics: {impressions: number; clicks: number} | null;
  }[]};
  local_viewer_activity: {rows: {creative_version: string; arrivals: number; completions: number; unattributed_arrivals: number}[]};
  proposal: {title: string; correction?: {label: string; note: string}};
};

export type Conversation = {
  id: string;
  campaign_id: string;
  settings: {model: string; mode: string};
  latest_message: number;
  latest_run_id: string | null;
  messages: {
    id: number; role: "user" | "assistant"; content: string; run_id: string;
    revision: number; catalog_id: string; kind: string; created_at: string;
    review?: ReviewEvidence; review_needs_refresh?: boolean;
  }[];
};
export type ConversationSummary = {id: string; title: string; model: string};

export function CampaignChat({conversation, busy}: {conversation: Conversation | null; busy: boolean}) {
  const messages = useRef<HTMLOListElement>(null);
  const latest = conversation?.latest_message;
  useEffect(() => {
    if (messages.current) messages.current.scrollTop = messages.current.scrollHeight;
  }, [latest]);
  return <div className="campaign-chat" aria-label="Campaign conversation">
    {conversation?.messages.length ? <ol ref={messages} aria-label="Saved messages" tabIndex={0}>
      {conversation.messages.map(message => <li key={message.id} className={`message message-${message.role}`}>
        <div className="message-heading">
          <strong>{message.role === "user" ? "You" : "Campaign agent"}</strong>
          <span>{message.role === "user" ? "From" : "At"} revision {message.revision}
            {message.kind === "needs_input" ? " · Question" : message.kind === "ready_for_review" ? " · Draft saved"
              : message.kind === "superseded" ? " · Superseded" : message.kind === "answered" ? " · Reply only"
                : message.kind === "needs_verification" ? " · Needs verification"
                  : message.kind === "waiting_for_evidence" ? " · Waiting for evidence" : ""}</span>
        </div>
        <p>{message.content}</p>
        {message.review && <details className="chat-evidence">
          <summary>Review evidence · revision {message.review.revision}{message.review_needs_refresh ? " · Refresh needed" : ""}</summary>
          <h3>Sample delivery · Fictional</h3>
          <p>{message.review.sample_delivery.label} · {message.review.sample_delivery.source} · {message.review.sample_delivery.coverage} coverage</p>
          <ul>{message.review.sample_delivery.rows.map(row => <li key={row.creative_version}>
            {row.creative_version}: {row.metrics ? `${row.metrics.impressions} impressions · ${row.metrics.clicks} clicks` : "Unknown · missing from sample report"}
          </li>)}</ul>
          <h3>Recorded local viewer activity</h3>
          <ul>{message.review.local_viewer_activity.rows.map(row => <li key={row.creative_version}>
            {row.creative_version}: {row.completions} of {row.arrivals} tagged visits completed
            {row.unattributed_arrivals > 0 && ` · ${row.unattributed_arrivals} unattributed visits excluded`}
          </li>)}</ul>
          <p>Viewer completions are counted separately from sample clicks. These observations do not establish causal lift.</p>
          {message.review.proposal.correction && <p>Saved buyer correction: {message.review.proposal.correction.label}.
            {message.review.proposal.correction.note && <> Buyer note: “{message.review.proposal.correction.note}”</>}</p>}
          <p className="review-reference">Review {message.review.id}</p>
        </details>}
      </li>)}
    </ol> : <p className="revision">Start a conversation about this campaign. Your messages and the agent’s replies will be saved here.</p>}
    {busy && <p className="chat-progress" role="status">The agent is working. Completed steps appear in Agent activity.</p>}
  </div>;
}
