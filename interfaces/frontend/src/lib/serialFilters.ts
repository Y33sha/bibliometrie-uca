/**
 * Registre des filtres de la liste des publications en série. Hors session admin, et sur la page d'un éditeur, la liste retient les publications en série qui ont des publications.
 */
import type { PresenceItem } from '#lib/components/filters/PresenceOptions.svelte';
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';
import { isAdmin } from '#lib/session.svelte.js';

/** Rubriques du panneau des filtres des publications en série, dans l'ordre d'affichage. */
export const SERIAL_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'serial', label: 'Publication en série' },
	{ key: 'curation', label: 'Curation' },
	{ key: 'lists', label: 'Listes' },
];

/**
 * Filtres de la liste.
 *
 * `publisherId` : éditeur de la page (onglet Revues d'un éditeur), imposé à la liste. `lists` : listes et classements servis par les décomptes, avec leurs niveaux.
 */
export function serialFilters(publisherId: number | undefined, lists: () => PresenceItem[]): ListFilter[] {
	return [
		{
			key: 'publisher',
			control: 'entity',
			label: filterLabels.publisher,
			param: 'publisher_id',
			group: 'serial',
			entity: 'publisher',
			fixed: () => (publisherId == null ? null : String(publisherId)),
		},
		{
			key: 'oaModels',
			control: 'checkbox',
			label: 'Modèles OA',
			param: 'oa_model',
			group: 'serial',
			facet: { type: 'labeled', apiKey: 'oa_models' },
		},
		{
			key: 'serialTypes',
			control: 'checkbox',
			label: filterLabels.types,
			param: 'serial_type',
			group: 'serial',
			facet: { type: 'labeled', apiKey: 'serial_types' },
		},
		{
			key: 'publications',
			control: 'checkbox',
			label: 'Publications',
			param: 'has_publications',
			group: 'curation',
			facet: { type: 'boolean', apiKey: 'publications', yesLabel: 'Avec', noLabel: 'Sans' },
			defaultSelection: () => ['yes'],
			// Une seule valeur filtre ; les deux cochées retiennent toutes les publications en série.
			serialize: (selected) => (selected.length === 1 ? selected[0] : null),
			fixed: () => (isAdmin() && publisherId == null ? null : 'yes'),
		},
		{
			key: 'lists',
			control: 'presence',
			label: filterLabels.lists,
			param: 'list_filter',
			levelsParam: 'list_level',
			group: 'lists',
			get items() {
				return lists();
			},
		},
	];
}
