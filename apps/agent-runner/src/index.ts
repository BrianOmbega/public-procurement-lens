import { executeAgentGraph } from './graph.js';

const main = async () => {
  const result = await executeAgentGraph({
    objective: 'Review the water supply procurement file and compare defensible evidence-only records.',
    sourceUrl: 'https://example.gov/publications/kisumu-water-supply-2024'
  });

  console.log(JSON.stringify(result, null, 2));
};

void main();
