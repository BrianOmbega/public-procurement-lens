import dotenv from 'dotenv';

dotenv.config();

export interface AppConfig {
  port: number;
  transport: string;
  storageConnectionString: string;
  auditLogPath: string;
  reportsPath: string;
  allowedSourceHosts: string[];
  environment: string;
}

const toNumber = (value: string | undefined, fallback: number): number => {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : fallback;
};

export const getConfig = (): AppConfig => ({
  port: toNumber(process.env.PORT, 3000),
  transport: process.env.MCP_TRANSPORT ?? 'streamable-http',
  storageConnectionString: process.env.STORAGE_CONNECTION_STRING ?? 'UseDevelopmentStorage=true',
  auditLogPath: process.env.AUDIT_LOG_PATH ?? './data/audit-events.jsonl',
  reportsPath: process.env.REPORTS_PATH ?? './data/draft-reports.jsonl',
  allowedSourceHosts: (process.env.ALLOWED_SOURCE_HOSTS ?? 'example.gov,opendata.go.ke')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean),
  environment: process.env.NODE_ENV ?? 'development'
});
