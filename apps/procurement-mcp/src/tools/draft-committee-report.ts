import { randomUUID } from 'node:crypto';
import { appendDraftReport } from '../storage.js';
import { getConfig } from '../config.js';
import type { DraftReportRequest, DraftCommitteeReport } from '@procurement/contracts';

export const draftCommitteeReport = (input: DraftReportRequest): DraftCommitteeReport => {
  const title = (input.title ?? '').trim();
  const summary = (input.summary ?? '').trim();
  const evidence = Array.isArray(input.evidence) ? input.evidence.filter(Boolean) : [];

  if (!title || !summary || evidence.length === 0) {
    throw new Error('Title, summary, and at least one evidence record are required.');
  }

  const report: DraftCommitteeReport = {
    reportId: randomUUID(),
    title,
    status: 'draft',
    createdAt: new Date().toISOString(),
    evidence,
    summary
  };

  appendDraftReport(report, getConfig().reportsPath);

  return report;
};
