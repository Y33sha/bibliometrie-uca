import { describe, it, expect, vi, beforeEach } from 'vitest';

let admin = false;
vi.mock('#lib/session.svelte.js', () => ({ isAdmin: () => admin }));

const { appendFilterParams, filterGroups, initialValues, isAvailable } = await import('./filterRegistry');
const { PERSON_FILTER_GROUPS, personFilters } = await import('./personFilters');

describe('personFilters', () => {
	beforeEach(() => {
		admin = false;
	});

	it('range chaque filtre des personnes dans une rubrique déclarée', () => {
		const filters = personFilters();
		expect(filterGroups(filters, PERSON_FILTER_GROUPS).flatMap((g) => g.filters)).toHaveLength(filters.length);
	});

	it('hors session admin, retient les personnes non exclues présentes dans la base RH, sans filtre de curation', () => {
		const filters = personFilters();
		const params = new URLSearchParams();
		appendFilterParams(filters, initialValues(filters), params);
		expect(Object.fromEntries(params)).toEqual({ has_rh: 'yes', exclusion: 'none' });
		expect(filters.filter(isAvailable).map((f) => f.key)).not.toContain('exclusion');
		expect(filters.filter(isAvailable).map((f) => f.key)).not.toContain('pending');
	});

	it('en session admin, propose les filtres de curation, exclusion « retenue » par défaut', () => {
		admin = true;
		const filters = personFilters();
		const values = initialValues(filters);
		expect(values.checkbox.exclusion).toEqual(['none']);
		expect(filters.filter(isAvailable).map((f) => f.key)).toEqual(expect.arrayContaining(['exclusion', 'pending']));
	});

	it("présélectionne le laboratoire de l'onglet d'un laboratoire", () => {
		expect(initialValues(personFilters(12)).checkbox.labs).toEqual(['12']);
	});
});
