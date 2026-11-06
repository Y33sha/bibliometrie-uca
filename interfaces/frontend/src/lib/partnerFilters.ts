/**
 * Registre des filtres des organisations partenaires d'une structure.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';
import { yearsFilter } from '#lib/sharedFilters.js';

/** Rubriques du panneau des filtres des organisations partenaires, dans l'ordre d'affichage. */
export const PARTNER_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'publication', label: 'Publication' },
	{ key: 'partner', label: 'Organisation' },
];

export const PARTNER_FILTERS: ListFilter[] = [
	yearsFilter('publication'),
	{
		key: 'countries',
		control: 'checkbox',
		label: filterLabels.countries,
		param: 'country',
		group: 'partner',
		facet: { type: 'labeled', apiKey: 'countries' },
		searchable: true,
	},
	{
		key: 'types',
		control: 'checkbox',
		label: filterLabels.types,
		param: 'type',
		group: 'partner',
		facet: { type: 'labeled', apiKey: 'types' },
	},
];
