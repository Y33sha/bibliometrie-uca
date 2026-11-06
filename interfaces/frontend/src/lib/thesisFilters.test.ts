import { describe, it, expect } from 'vitest';
import { filterGroups, isAvailable } from './filterRegistry';
import { THESIS_FILTER_GROUPS, thesisFilters } from './thesisFilters';

describe('thesisFilters', () => {
	it('range chaque filtre des thèses dans une rubrique déclarée', () => {
		const filters = thesisFilters();
		expect(filterGroups(filters, THESIS_FILTER_GROUPS).flatMap((g) => g.filters)).toHaveLength(filters.length);
	});

	it("impose le laboratoire de l'onglet d'un laboratoire, et retire son filtre", () => {
		const labs = thesisFilters(12).find((f) => f.key === 'labs')!;
		expect(labs.fixed?.()).toBe('12');
		expect(isAvailable(labs)).toBe(false);
	});
});
