import { describe, it, expect } from 'vitest';
import { filterGroups, type CheckboxFilter } from './filterRegistry';
import { PUBLICATION_FILTER_GROUPS, labsFilter, publicationFilters } from './publicationFilters';
import type { PublicationListContext } from './publicationListContext';

describe('labsFilter', () => {
	const normalize = (labsFilter('authors', () => null) as CheckboxFilter).normalize!;

	it('« Aucun labo » cochée décoche les laboratoires', () => {
		expect(normalize(['12', '15', 'none'])).toEqual(['none']);
	});

	it('un laboratoire coché décoche « Aucun labo »', () => {
		expect(normalize(['none', '12'])).toEqual(['12']);
		expect(normalize(['12', '15'])).toEqual(['12', '15']);
	});
});

describe('publicationFilters', () => {
	it('range chaque filtre des publications dans une rubrique déclarée', () => {
		const contexts: PublicationListContext[] = [{ kind: 'all' }, { kind: 'lab', id: 1 }, { kind: 'person', id: 1 }];
		for (const context of contexts) {
			const filters = publicationFilters(context);
			expect(filterGroups(filters, PUBLICATION_FILTER_GROUPS).flatMap((g) => g.filters)).toHaveLength(filters.length);
		}
	});
});
