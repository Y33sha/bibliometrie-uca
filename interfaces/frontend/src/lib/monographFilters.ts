/**
 * Registre des filtres de la liste des monographies.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';
import { yearsFilter } from '#lib/sharedFilters.js';

/** Rubriques du panneau des filtres des monographies, dans l'ordre d'affichage. */
export const MONOGRAPH_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'monograph', label: 'Monographie' },
	{ key: 'venue', label: 'Éditeur et collection' },
];

/** Filtres de la liste. `publisherId`, `serialId` : éditeur ou collection de la page, imposés à la liste. */
export function monographFilters(publisherId?: number, serialId?: number): ListFilter[] {
	return [
		{
			key: 'kinds',
			control: 'checkbox',
			label: filterLabels.types,
			param: 'type',
			group: 'monograph',
			facet: { type: 'label_map', apiKey: 'kinds', labels: { book: 'Livres', proceedings: "Volumes d'actes" } },
		},
		yearsFilter('monograph'),
		{
			key: 'publisher',
			control: 'entity',
			label: filterLabels.publisher,
			param: 'publisher_id',
			group: 'venue',
			entity: 'publisher',
			fixed: () => (publisherId == null ? null : String(publisherId)),
		},
		{
			key: 'serial',
			control: 'entity',
			label: 'Collections',
			param: 'serial_id',
			group: 'venue',
			entity: 'serial',
			fixed: () => (serialId == null ? null : String(serialId)),
		},
	];
}
