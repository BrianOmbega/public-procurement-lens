export interface BorrowedFetchResult {
  status: 'ok';
  sourceUrl: string;
  retrievedAt: string;
  bodySnippet: string;
}

export const fetchApprovedSource = async (sourceUrl: string): Promise<BorrowedFetchResult> => {
  const safeUrl = sourceUrl.trim();
  if (!safeUrl) {
    throw new Error('A valid source URL is required.');
  }

  return {
    status: 'ok',
    sourceUrl: safeUrl,
    retrievedAt: new Date().toISOString(),
    bodySnippet: 'Approved public procurement excerpt from a synthetic evaluation fixture.'
  };
};
