import { procurementFixtureData, type ComparisonRequest, type ComparablePriceResult } from '@procurement/contracts';

export const compareComparablePrices = (input: ComparisonRequest): ComparablePriceResult => {
  const itemCategory = (input.itemCategory ?? '').trim();
  const unit = (input.unit ?? '').trim();
  const quantity = Number(input.quantity ?? 0);
  const currency = input.currency ?? 'KES';

  if (!itemCategory || !unit || !quantity || !currency) {
    throw new Error('itemCategory, unit, quantity, and currency are required for price comparison.');
  }

  const candidateData = procurementFixtureData.filter((award) => {
    const sameCategory = award.itemCategory.toLowerCase() === itemCategory.toLowerCase();
    const sameUnit = award.unit.toLowerCase() === unit.toLowerCase();
    const sameCurrency = award.currency === currency;
    const sameLocation = !input.location || award.location.toLowerCase() === input.location.toLowerCase();
    const sameScope = !input.contractScope || award.contractScope.toLowerCase() === input.contractScope.toLowerCase();

    return sameCategory && sameUnit && sameCurrency && sameLocation && sameScope;
  });

  const comparableRecords = candidateData.length > 0 ? candidateData : [];
  const unitPrices = comparableRecords.map((record) => record.awardValue / record.quantity);

  const median = (values: number[]) => {
    if (values.length === 0) return 0;
    const cloned = [...values].sort((a, b) => a - b);
    const midpoint = Math.floor(cloned.length / 2);
    if (cloned.length % 2 === 0) {
      return (cloned[midpoint - 1] + cloned[midpoint]) / 2;
    }
    return cloned[midpoint];
  };

  const excluded = procurementFixtureData.filter((record) => !comparableRecords.some((item) => item.id === record.id)).map((record) => ({
    id: record.id,
    reason: 'Not sufficiently comparable for requested unit, location, or contract scope.'
  }));

  return {
    comparableRecords,
    excludedRecords: excluded,
    comparisonCount: comparableRecords.length,
    summary: {
      averageUnitPrice: unitPrices.length > 0 ? unitPrices.reduce((sum, value) => sum + value, 0) / unitPrices.length : 0,
      medianUnitPrice: median(unitPrices),
      comparisonCount: comparableRecords.length
    }
  };
};
