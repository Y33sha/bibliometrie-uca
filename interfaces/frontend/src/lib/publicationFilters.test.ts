import { describe, it, expect } from 'vitest';
import { filterGroups } from './filterRegistry';
import { PUBLICATION_FILTER_GROUPS, publicationFilters } from './publicationFilters';
import type { PublicationListContext } from './publicationListContext';

describe('publicationFilters', () => {
	it('range chaque filtre des publications dans une rubrique déclarée', () => {
		const contexts: PublicationListContext[] = [{ kind: 'all' }, { kind: 'lab', id: 1 }, { kind: 'person', id: 1 }];
		for (const context of contexts) {
			const filters = publicationFilters(context);
			expect(filterGroups(filters, PUBLICATION_FILTER_GROUPS).flatMap((g) => g.filters)).toHaveLength(filters.length);
		}
	});
});
