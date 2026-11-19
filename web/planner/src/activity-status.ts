/** Execution failure labels never change the durable run or authorize retries. */
export function activityFailureStatus(busy: boolean, recorded?: string, code?: string): string | null {
  if (busy) return null;
  if (recorded === "unknown" || code && ["inference_outcome_unknown", "request_outcome_unavailable"].includes(code)) {
    return "Provider outcome unknown · no automatic retry";
  }
  if (code && ["waiting_for_credentials", "credential_mismatch", "connection_expired", "sign_in_required"].includes(code)) {
    return "Connection required · resume the original request";
  }
  if (code === "provider_rate_limited") return "Rate limited · inspect diagnostics";
  if (recorded === "failed" || code !== undefined) return "Request failed · inspect diagnostics";
  return null;
}
