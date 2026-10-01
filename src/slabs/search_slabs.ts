import MiniSearch from 'minisearch';

import { type Slab, loadSlabs } from './slab.ts';

let index: MiniSearch<Slab> | null = null;

const slabIndex = () => {
  if (index == null) {
    index = new MiniSearch<Slab>({
      fields: ['id', 'title', 'description', 'tags', 'prompts', 'columnNames'],
      extractField: (slab, field) => {
        if (field === 'columnNames') {
          return Object.keys(slab.columns).join(' ');
        }
        const value =
          slab[field as 'id' | 'title' | 'description' | 'tags' | 'prompts'];
        return Array.isArray(value) ? value.join(' ') : value;
      },
      tokenize: (text) =>
        text.split(/[^a-z0-9]+/i).filter((token) => token.length > 0),
      searchOptions: {
        boost: { title: 3, tags: 2, prompts: 2, id: 2 },
        fuzzy: 0.2,
        prefix: true,
        combineWith: 'OR',
      },
    });
    index.addAll(loadSlabs());
  }
  return index;
};

export const slabSummary = (slab: Slab) => ({
  slab: slab.id,
  title: slab.title,
  description: slab.description,
  params: Object.fromEntries(
    Object.entries(slab.subs).map(([name, sub]) => [
      name,
      {
        type: sub.type,
        description: sub.description,
        default: sub.default,
        enum: sub.enum,
      },
    ]),
  ),
  columns: slab.columns,
});

export const searchSlabs = (query: string, limit = 5) => {
  const slabs = new Map(loadSlabs().map((slab) => [slab.id, slab]));
  const hits = slabIndex().search(query).slice(0, limit);
  return hits.map((hit) => ({
    score: Math.round(hit.score * 100) / 100,
    ...slabSummary(slabs.get(String(hit.id)) as Slab),
  }));
};
