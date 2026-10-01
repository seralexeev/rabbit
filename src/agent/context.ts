import { stringify } from 'yaml';

import { listRuns } from '../runs.ts';
import { searchSlabs } from '../slabs/search_slabs.ts';

export const groundingContext = async (question: string) => {
  const runs = await listRuns(10);
  const slabs = searchSlabs(question, 5);
  return `# Recent runs\n\n${stringify(runs)}\n# Nearest slabs\n\n${stringify(slabs)}`;
};
