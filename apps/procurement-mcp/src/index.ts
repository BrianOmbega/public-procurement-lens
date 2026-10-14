import cors from 'cors';
import express, { type Request, type Response } from 'express';
import { randomUUID } from 'node:crypto';
import { appendAuditEvent, appendDraftReport, sanitizeAuditPayload } from './storage.js';
import { getConfig } from './config.js';
import { searchHistoricalAwards } from './tools/search-historical-awards.js';
import { compareComparablePrices } from './tools/compare-comparable-prices.js';
import { draftCommitteeReport } from './tools/draft-committee-report.js';
import type { AuditEvent } from '@procurement/contracts';

const config = getConfig();
const app = express();
const serverState = {
  initialized: false,
  sessionId: randomUUID()
};

app.use(cors());
app.use(express.json({ limit: '1mb' }));

const writeAudit = (event: Omit<AuditEvent, 'eventId' | 'timestamp'> & Partial<Pick<AuditEvent, 'timestamp'>>) => {
  const safeEvent: AuditEvent = {
    eventId: randomUUID(),
    timestamp: new Date().toISOString(),
    ...event,
    input: sanitizeAuditPayload(event.input ?? {}) as Record<string, unknown>,
    output: sanitizeAuditPayload(event.output ?? {}) as Record<string, unknown>
  };
  appendAuditEvent(safeEvent, config.auditLogPath);
  return safeEvent;
};

const errorResponse = (code: string, message: string, details: unknown = null) => ({
  error: { code, message, details }
});

app.get('/healthz', (_req: Request, res: Response) => {
  res.status(200).json({ status: 'ok' });
});

app.get('/readyz', (_req: Request, res: Response) => {
  res.status(200).json({
    status: 'ready',
    dependencies: {
      storage: config.storageConnectionString ? 'ok' : 'missing',
      transport: config.transport
    }
  });
});

app.post('/mcp', async (req: Request, res: Response) => {
  const body = req.body ?? {};

  if (!body || typeof body !== 'object') {
    return res.status(400).json(errorResponse('VALIDATION_ERROR', 'Request could not be processed', null));
  }

  const { method, params, id } = body;
  if (method === 'initialize') {
    serverState.initialized = true;
    return res.status(200).json({
      jsonrpc: '2.0',
      id,
      result: {
        protocolVersion: '2024-11-05',
        capabilities: {
          tools: { listChanged: false }
        },
        serverInfo: {
          name: 'public-procurement-lens-mcp',
          version: '0.1.0'
        },
        tools: [
          {
            name: 'search_historical_awards',
            description: 'Search approved procurement history',
            inputSchema: {
              type: 'object',
              properties: {
                query: { type: 'string' },
                itemCategory: { type: 'string' },
                location: { type: 'string' },
                limit: { type: 'number' }
              },
              required: ['query']
            }
          },
          {
            name: 'compare_comparable_prices',
            description: 'Compare only defensibly similar prices',
            inputSchema: {
              type: 'object',
              properties: {
                itemCategory: { type: 'string' },
                unit: { type: 'string' },
                quantity: { type: 'number' },
                currency: { type: 'string', enum: ['KES', 'USD'] },
                location: { type: 'string' },
                contractScope: { type: 'string' }
              },
              required: ['itemCategory', 'unit', 'quantity', 'currency']
            }
          },
          {
            name: 'draft_committee_report',
            description: 'Create a versioned review draft report',
            inputSchema: {
              type: 'object',
              properties: {
                title: { type: 'string' },
                summary: { type: 'string' },
                evidence: { type: 'array', items: { type: 'string' } }
              },
              required: ['title', 'summary', 'evidence']
            }
          }
        ]
      }
    });
  }

  if (method === 'tools/call') {
    const { name, arguments: toolArgs } = params ?? {};
    try {
      let result: unknown;
      switch (name) {
        case 'search_historical_awards':
          result = searchHistoricalAwards(toolArgs ?? {});
          break;
        case 'compare_comparable_prices':
          result = compareComparablePrices(toolArgs ?? {});
          break;
        case 'draft_committee_report':
          result = draftCommitteeReport(toolArgs ?? {});
          break;
        default:
          throw new Error(`Unsupported tool: ${String(name)}`);
      }

      writeAudit({
        actor: 'local-agent-runner',
        correlationId: randomUUID(),
        tool: String(name),
        outcome: 'success',
        input: toolArgs ?? {},
        output: result as Record<string, unknown>
      });

      return res.status(200).json({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] } });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unknown tool error';
      writeAudit({
        actor: 'local-agent-runner',
        correlationId: randomUUID(),
        tool: String(name ?? 'unknown'),
        outcome: 'failure',
        input: (toolArgs ?? {}) as Record<string, unknown>,
        output: { error: message },
        error: message
      });
      return res.status(400).json({ jsonrpc: '2.0', id, error: { code: 'VALIDATION_ERROR', message } });
    }
  }

  return res.status(400).json(errorResponse('VALIDATION_ERROR', 'Unsupported MCP method'));
});

app.post('/api/audit-events', (req: Request, res: Response) => {
  try {
    const payload = req.body ?? {};
    if (!payload || typeof payload !== 'object') {
      return res.status(400).json(errorResponse('VALIDATION_ERROR', 'Request could not be processed', null));
    }

    const event = payload as Record<string, unknown>;
    const normalized = {
      eventId: String(event.eventId ?? randomUUID()),
      correlationId: String(event.correlationId ?? randomUUID()),
      actor: String(event.actor ?? 'unknown'),
      tool: String(event.tool ?? 'unknown'),
      timestamp: String(event.timestamp ?? new Date().toISOString()),
      outcome: event.outcome === 'failure' ? 'failure' : 'success',
      input: (event.input ?? {}) as Record<string, unknown>,
      output: (event.output ?? {}) as Record<string, unknown>,
      ...(event.error ? { error: String(event.error) } : {})
    };

    appendAuditEvent(normalized as AuditEvent, config.auditLogPath);
    return res.status(202).json({ accepted: true, eventId: normalized.eventId });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown audit error';
    return res.status(500).json(errorResponse('INTERNAL_ERROR', 'Request could not be processed', message));
  }
});

app.listen(config.port, () => {
  console.log(`Procurement MCP server listening on http://localhost:${config.port}`);
});

export { app, serverState };
