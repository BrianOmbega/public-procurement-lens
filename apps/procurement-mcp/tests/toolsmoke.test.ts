import { describe, expect, it } from 'vitest';
import { searchHistoricalAwards } from '../src/tools/search-historical-awards.js';
import { compareComparablePrices } from '../src/tools/compare-comparable-prices.js';
import { draftCommitteeReport } from '../src/tools/draft-committee-report.js';

describe('procurement assessment tools', () => {
  it('searches approved historical awards', () => {
    const result = searchHistoricalAwards({ query: 'water', itemCategory: 'valves', limit: 5 });
    expect(result.results.length).toBeGreaterThan(0);
    expect(result.results[0].itemCategory).toBe('valves');
  });

  it('compares comparable prices using a narrow filter', () => {
    const result = compareComparablePrices({
      itemCategory: 'valves',
      unit: 'piece',
      quantity: 120,
      currency: 'KES',
      location: 'Kisumu',
      contractScope: 'rural water project'
    });

    expect(result.comparisonCount).toBeGreaterThan(0);
    expect(result.summary.averageUnitPrice).toBeGreaterThan(0);
  });

  it('creates a draft report with evidence', () => {
    const result = draftCommitteeReport({
      title: 'Review of water supply valve award',
      summary: 'The proposal is a draft committee review for a water supply award.',
      evidence: ['https://example.gov/publications/kisumu-water-supply-2024']
    });

    expect(result.status).toBe('draft');
    expect(result.evidence.length).toBe(1);
  });
});
