import fs from 'node:fs';
import path from 'node:path';
import type { AuditEvent, DraftCommitteeReport } from '@procurement/contracts';

const ensureDirectory = (targetPath: string): void => {
  const directory = path.dirname(targetPath);
  fs.mkdirSync(directory, { recursive: true });
};

export const appendAuditEvent = (event: AuditEvent, filePath: string): void => {
  ensureDirectory(filePath);
  fs.appendFileSync(filePath, `${JSON.stringify(event)}\n`, 'utf8');
};

export const appendDraftReport = (report: DraftCommitteeReport, filePath: string): void => {
  ensureDirectory(filePath);
  fs.appendFileSync(filePath, `${JSON.stringify(report)}\n`, 'utf8');
};

export const sanitizeAuditPayload = <T extends Record<string, unknown>>(payload: T): T => {
  const redacted = { ...payload };
  if ('credentials' in redacted) {
    delete redacted.credentials;
  }
  if ('token' in redacted) {
    delete redacted.token;
  }
  if ('password' in redacted) {
    delete redacted.password;
  }
  return redacted;
};
