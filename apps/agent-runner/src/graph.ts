import { randomUUID } from 'node:crypto';
import { fetchApprovedSource } from './borrowed-fetch-client.js';
import { submitAuditEvent } from './audit-client.js';
import { runLocalModel } from './model.js';

export interface RunnerRequest {
  objective: string;
  sourceUrl: string;
}

export const executeAgentGraph = async ({ objective, sourceUrl }: RunnerRequest) => {
  const source = await fetchApprovedSource(sourceUrl);
  const modelResult = await runLocalModel({
    prompt: `Assess the procurement context and draft a safe summary: ${objective}`
  });

  const correlationId = randomUUID();
  const eventId = randomUUID();

  await submitAuditEvent({
    eventId,
    correlationId,
    actor: 'local-agent-runner',
    tool: 'agent_graph',
    timestamp: new Date().toISOString(),
    outcome: 'success',
    input: { objective, sourceUrl },
    output: { source, model: modelResult }
  });

  return {
    correlationId,
    source,
    model: modelResult,
    eventId
  };
};
