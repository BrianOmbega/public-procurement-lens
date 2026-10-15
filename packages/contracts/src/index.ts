export type AgreementStatus = 'draft' | 'approved' | 'rejected';

export interface HistoricalAwardRecord {
  id: string;
  title: string;
  procuringEntity: string;
  itemCategory: string;
  unit: string;
  quantity: number;
  currency: 'KES' | 'USD';
  awardValue: number;
  awardDate: string;
  sourceUrl: string;
  contractScope: string;
  location: string;
}

export interface ComparablePriceResult {
  comparableRecords: HistoricalAwardRecord[];
  excludedRecords: Array<{ id: string; reason: string }>;
  comparisonCount: number;
  summary: {
    averageUnitPrice: number;
    medianUnitPrice: number;
    comparisonCount: number;
  };
}

export interface AuditEvent {
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

export interface DraftCommitteeReport {
  reportId: string;
  title: string;
  status: AgreementStatus;
  createdAt: string;
  evidence: string[];
  summary: string;
}

export interface SearchHistoricalAwardsRequest {
  query: string;
  itemCategory?: string;
  location?: string;
  limit?: number;
}

export interface ComparisonRequest {
  itemCategory: string;
  unit: string;
  quantity: number;
  currency: 'KES' | 'USD';
  location?: string;
  contractScope?: string;
}

export interface DraftReportRequest {
  title: string;
  summary: string;
  evidence: string[];
}

export const procurementFixtureData: HistoricalAwardRecord[] = [
  {
    id: 'A-001',
    title: 'Rural water supply valves',
    procuringEntity: 'Kisumu County',
    itemCategory: 'valves',
    unit: 'piece',
    quantity: 120,
    currency: 'KES',
    awardValue: 972000,
    awardDate: '2024-02-15',
    sourceUrl: 'https://example.gov/publications/kisumu-water-supply-2024',
    contractScope: 'rural water project',
    location: 'Kisumu'
  },
  {
    id: 'A-002',
    title: 'Electrical conduit couplings',
    procuringEntity: 'Kakamega County',
    itemCategory: 'electrical fittings',
    unit: 'piece',
    quantity: 180,
    currency: 'KES',
    awardValue: 1140000,
    awardDate: '2024-04-22',
    sourceUrl: 'https://example.gov/publications/kakamega-electrical-2024',
    contractScope: 'county electrification',
    location: 'Kakamega'
  },
  {
    id: 'A-003',
    title: 'Laboratory reagent bottles',
    procuringEntity: 'Nakuru County',
    itemCategory: 'laboratory supplies',
    unit: 'piece',
    quantity: 400,
    currency: 'KES',
    awardValue: 1460000,
    awardDate: '2024-06-12',
    sourceUrl: 'https://example.gov/publications/nakuru-lab-supplies-2024',
    contractScope: 'public health lab',
    location: 'Nakuru'
  }
];
