import { afterEach, describe, expect, it, vi } from 'vitest';
import { submitAuditEvent, type AuditPayload } from '../src/audit-client.js';

const payload: AuditPayload = {
  eventId: 'event-1',
  correlationId: 'correlation-1',
  actor: 'test-runner',
  tool: 'test-tool',
  timestamp: '2026-10-11T00:00:00.000Z',
  outcome: 'success',
  input: {},
  output: {}
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('submitAuditEvent', () => {
  it('posts the event and returns the service response', async () => {
    vi.stubEnv('AGENT_AUDIT_URL', 'http://localhost:3000/api/audit-events');
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ accepted: true, eventId: payload.eventId }, { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitAuditEvent(payload)).resolves.toEqual({ accepted: true, eventId: payload.eventId });
    expect(fetchMock).toHaveBeenCalledWith('http://localhost:3000/api/audit-events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(payload)
    });
  });

  it('rejects unsuccessful service responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 500 })));

    await expect(submitAuditEvent(payload)).rejects.toThrow('Audit service request failed with status 500.');
  });
});