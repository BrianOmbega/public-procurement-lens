import { procurementFixtureData, type SearchHistoricalAwardsRequest } from '@procurement/contracts';

export const searchHistoricalAwards = (input: SearchHistoricalAwardsRequest) => {
  const query = (input.query ?? '').trim().toLowerCase();
  if (!query) {
    throw new Error('A search query is required.');
  }

  const normalized = procurementFixtureData.filter((award) => {
    const haystack = [
      award.title,
      award.procuringEntity,
      award.itemCategory,
      award.location,
      award.contractScope
    ]
      .join(' ')
      .toLowerCase();

    return haystack.includes(query);
  });

  const itemCategory = input.itemCategory?.trim();
  const location = input.location?.trim();

  const filtered = normalized.filter((award) => {
    const matchesCategory = !itemCategory || award.itemCategory.toLowerCase() === itemCategory.toLowerCase();
    const matchesLocation = !location || award.location.toLowerCase() === location.toLowerCase();
    return matchesCategory && matchesLocation;
  });

  const limit = Number.isFinite(input.limit) ? Math.max(1, Math.trunc(input.limit ?? 5)) : 5;

  return {
    query,
    results: filtered.slice(0, limit).map((award) => ({
      id: award.id,
      title: award.title,
      procuringEntity: award.procuringEntity,
      itemCategory: award.itemCategory,
      location: award.location,
      awardValue: award.awardValue,
      awardDate: award.awardDate,
      sourceUrl: award.sourceUrl
    })),
    count: filtered.length
  };
};
