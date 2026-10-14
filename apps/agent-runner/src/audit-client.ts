export interface AuditPayload {
  eventId: string;
  correlationId: string;
  actor: string;
  tool: string;
  timestamp: string;
  outcome: 'success' | 'failure';
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error?: string;
}

export const submitAuditEvent = async (payload: AuditPayload): Promise<{ accepted: boolean; eventId: string }> => {
  const url = process.env.AGENT_AUDIT_URL ?? 'http://localhost:3000/api/audit-events';
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    throw new Error(`Audit service request failed with status ${response.status}.`);
  }

  const result = await response.json() as { accepted?: unknown; eventId?: unknown };
  if (result.accepted !== true || result.eventId !== payload.eventId) {
    throw new Error('Audit service returned an invalid response.');
  }

  return { accepted: true, eventId: payload.eventId };
};
