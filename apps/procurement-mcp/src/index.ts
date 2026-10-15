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

const INDEX_HTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Public Procurement Lens - MCP Service</title>
<style>
 body{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;background:#0b1020;color:#e6e9f2;margin:0;padding:2.5rem}
 main{max-width:860px;margin:0 auto}
 h1{font-size:1.5rem;margin:0 0 .35rem} p.sub{color:#9aa4c0;margin:0 0 1.6rem}
 code{background:#151c33;padding:.15rem .4rem;border-radius:4px;font-size:.86rem}
 table{width:100%;border-collapse:collapse;margin:0 0 1.6rem;font-size:.92rem}
 td,th{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #1d2542}
 th{color:#9aa4c0;font-weight:600}
 button{background:#3b82f6;color:#fff;border:0;border-radius:8px;padding:.7rem 1.1rem;font-size:.95rem;cursor:pointer}
 button:hover{background:#2f6fe0}
 pre{background:#0f1528;border:1px solid #1d2542;border-radius:8px;padding:1rem;overflow:auto;font-size:.82rem;max-height:340px}
 .note{background:#2a1f0b;border:1px solid #6b4f14;border-radius:8px;padding:.8rem 1rem;font-size:.88rem;color:#f0d9a0;margin-bottom:1.6rem}
</style></head><body><main>
<h1>Public Procurement Lens &mdash; Procurement MCP Service</h1>
<p class="sub">TypeScript API workspace &middot; Node/Express &middot; MCP over HTTP</p>
<div class="note"><strong>Honest scope:</strong> this workspace is scaffold-level. Its source-fetch and model
adapters return <em>synthetic</em> data, and it has no authentication middleware. It proves route behaviour and
runner-to-backend audit transport only. The genuine end-to-end agent is the Python implementation
(<code>./run.sh</code>), whose audit trail is machine-verified by <code>lens-audit verify</code>.</div>
<table>
<tr><th>Method</th><th>Path</th><th>Purpose</th></tr>
<tr><td>GET</td><td><code>/healthz</code></td><td>Liveness probe</td></tr>
<tr><td>GET</td><td><code>/readyz</code></td><td>Readiness + dependency status</td></tr>
<tr><td>POST</td><td><code>/mcp</code></td><td>JSON-RPC 2.0 <code>tools/call</code></td></tr>
<tr><td>POST</td><td><code>/api/audit-events</code></td><td>Append an audit event (credentials stripped)</td></tr>
</table>
<p><strong>MCP tools:</strong> <code>search-historical-awards</code> &middot;
<code>compare-comparable-prices</code> &middot; <code>draft-committee-report</code></p>
<button id="run">Try the MCP search tool</button>
<pre id="out">Click the button to fire a live tools/call request.</pre>
<script>
document.getElementById('run').addEventListener('click', async () => {
  const out = document.getElementById('out');
  out.textContent = 'Requesting...';
  try {
    const r = await fetch('/mcp', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: '1', method: 'tools/call',
        params: { name: 'search_historical_awards', arguments: { query: 'water' } } })
    });
    out.textContent = 'HTTP ' + r.status + '\\n' + JSON.stringify(await r.json(), null, 2);
  } catch (e) { out.textContent = 'Error: ' + e.message; }
});
</script>
</main></body></html>`;

app.get('/', (_req: Request, res: Response) => {
  res.status(200).type('html').send(INDEX_HTML);
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
