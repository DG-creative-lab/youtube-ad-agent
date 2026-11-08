import {useEffect, useRef} from "react";

export type Conversation = {
  id: string;
  campaign_id: string;
  settings: {model: string; mode: string};
  latest_message: number;
  latest_run_id: string | null;
  messages: {
    id: number; role: "user" | "assistant"; content: string; run_id: string;
    revision: number; catalog_id: string; kind: string; created_at: string;
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
                : message.kind === "needs_verification" ? " · Needs verification" : ""}</span>
        </div>
        <p>{message.content}</p>
      </li>)}
    </ol> : <p className="revision">Start a conversation about this campaign. Your messages and the agent’s replies will be saved here.</p>}
    {busy && <p className="chat-progress" role="status">The agent is working. Completed steps appear in Agent activity.</p>}
  </div>;
}
