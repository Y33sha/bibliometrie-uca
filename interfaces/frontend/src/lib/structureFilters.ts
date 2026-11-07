/**
 * Registre des filtres de la liste des structures. La liste part des types de structure configurés comme laboratoires et du périmètre des personnes. Seule la session admin change le périmètre.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';
import type { LabListDefaults } from '#lib/labListDefaults.js';
import { isAdmin } from '#lib/session.svelte.js';
import { STRUCTURE_TYPES } from '#lib/structureTypes.js';

/** Rubriques du panneau des filtres des structures, dans l'ordre d'affichage. */
export const STRUCTURE_FILTER_GROUPS: readonly FilterGroup[] = [{ key: 'structure', label: 'Structure' }];

/** Filtres de la liste. `defaults` : sélection à l'ouverture de la page. */
export function structureFilters(defaults: LabListDefaults): ListFilter[] {
	return [
		{
			key: 'perimeters',
			control: 'checkbox',
			label: 'Périmètres',
			param: 'perimeter_id',
			group: 'structure',
			// `none` désigne les structures hors de tout périmètre, comme dans le paramètre `perimeter_id` de l'API.
			facet: { type: 'labeled', apiKey: 'perimeters' },
			single: true,
			defaultSelection: () => defaults.perimeters,
			fixed: () => (isAdmin() ? null : defaults.perimeters.join(',') || null),
		},
		{
			key: 'types',
			control: 'checkbox',
			label: filterLabels.types,
			param: 'structure_type',
			group: 'structure',
			facet: { type: 'label_map', apiKey: 'types', labels: Object.fromEntries(STRUCTURE_TYPES.map((t) => [t.value, t.label])) },
			defaultSelection: () => defaults.types,
		},
		{
			key: 'tutelles',
			control: 'checkbox',
			label: 'Tutelles',
			param: 'tutelle_id',
			group: 'structure',
			facet: { type: 'labeled', apiKey: 'tutelles' },
			searchable: true,
		},
	];
}
