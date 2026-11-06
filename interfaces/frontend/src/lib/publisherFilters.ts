/**
 * Registre des filtres de la liste des éditeurs. Hors session admin, la liste retient les éditeurs qui ont des publications.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';
import { hasPublicationsFilter } from '#lib/sharedFilters.js';
import { isAdmin } from '#lib/session.svelte.js';

/** Rubriques du panneau des filtres des éditeurs, dans l'ordre d'affichage. */
export const PUBLISHER_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'publisher', label: 'Éditeur' },
	{ key: 'curation', label: 'Curation' },
];

export const PUBLISHER_FILTERS: ListFilter[] = [
	{
		key: 'publisherTypes',
		control: 'checkbox',
		label: filterLabels.types,
		param: 'publisher_type',
		group: 'publisher',
		facet: { type: 'labeled', apiKey: 'publisher_types' },
	},
	{
		key: 'countries',
		control: 'checkbox',
		label: filterLabels.countries,
		param: 'country',
		group: 'publisher',
		facet: { type: 'labeled', apiKey: 'countries' },
		searchable: true,
	},
	hasPublicationsFilter('curation', isAdmin),
];
