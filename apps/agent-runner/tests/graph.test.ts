import { describe, expect, it, vi } from 'vitest';
import { executeAgentGraph } from '../src/graph.js';

vi.mock('../src/audit-client.js', () => ({
  submitAuditEvent: vi.fn(async (payload: { eventId: string }) => ({ accepted: true, eventId: payload.eventId }))
}));

describe('agent-runner graph', () => {
  it('executes the local graph with synthetic source data', async () => {
    const result = await executeAgentGraph({
      objective: 'Validate a synthetic procurement review.',
      sourceUrl: 'https://example.gov/publications/kisumu-water-supply-2024'
    });

    expect(result.model.model).toBeDefined();
    expect(result.source.status).toBe('ok');
  });
});
