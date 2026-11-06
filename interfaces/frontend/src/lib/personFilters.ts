/**
 * Registre des filtres de l'annuaire des personnes. La session admin y gagne les filtres À confirmer et Exclusions ; hors session admin, l'annuaire retient les personnes non exclues.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { IDENTIFIER_ITEMS, PENDING_ITEMS } from '#lib/filterItems.js';
import { personExclusionLabels, staffCategoryLabels } from '#lib/labels.js';
import { isAdmin } from '#lib/session.svelte.js';

/** Rubriques du panneau des filtres des personnes, dans l'ordre d'affichage. */
export const PERSON_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'affiliation', label: 'Affectation' },
	{ key: 'identifiers', label: 'Identifiants' },
	{ key: 'curation', label: 'Curation' },
];

/** Paramètre de requête de chaque identifiant, et de chaque élément à confirmer. */
const IDENTIFIER_PARAMS: Record<string, string> = { orcid: 'has_orcid', idhal: 'has_idhal', idref: 'has_idref' };
const PENDING_PARAMS: Record<string, string> = {
	pending_forms: 'has_pending_forms',
	pending_identifiers: 'has_pending_identifiers',
};

/** Filtres de l'annuaire. `labId` : laboratoire de la page (onglet Personnes d'un laboratoire), présélectionné dans le filtre Laboratoires. */
export function personFilters(labId?: number): ListFilter[] {
	return [
		{
			key: 'rh',
			control: 'checkbox',
			label: 'Base RH',
			param: 'has_rh',
			group: 'affiliation',
			facet: { type: 'boolean', apiKey: 'rh', yesLabel: 'Oui', noLabel: 'Non' },
			defaultSelection: () => ['yes'],
			// Une seule valeur filtre ; les deux cochées retiennent tout le monde.
			serialize: (selected) => (selected.length === 1 ? selected[0] : null),
		},
		{
			key: 'categories',
			control: 'checkbox',
			label: 'Catégories',
			param: 'category',
			group: 'affiliation',
			facet: { type: 'label_map', apiKey: 'categories', labels: staffCategoryLabels },
		},
		{
			key: 'labs',
			control: 'checkbox',
			label: 'Laboratoires',
			param: 'laboratory',
			group: 'affiliation',
			facet: { type: 'labeled', apiKey: 'laboratories' },
			searchable: true,
			...(labId == null ? {} : { defaultSelection: () => [String(labId)] }),
		},
		{
			key: 'identifiers',
			control: 'presence',
			label: 'Identifiants',
			param: 'id_filter',
			group: 'identifiers',
			items: IDENTIFIER_ITEMS,
			itemParams: IDENTIFIER_PARAMS,
		},
		{
			key: 'pending',
			control: 'presence',
			label: 'À confirmer',
			param: 'pending_filter',
			group: 'curation',
			items: PENDING_ITEMS,
			itemParams: PENDING_PARAMS,
			enabled: isAdmin,
		},
		{
			key: 'exclusion',
			control: 'checkbox',
			label: 'Exclusions',
			param: 'exclusion',
			group: 'curation',
			// `none` désigne les personnes retenues, comme dans le paramètre `exclusion` de l'API.
			facet: {
				type: 'fixed',
				options: [
					{ value: 'none', text: 'Retenue' },
					...Object.entries(personExclusionLabels).map(([value, text]) => ({ value, text })),
				],
			},
			defaultSelection: () => ['none'],
			fixed: () => (isAdmin() ? null : 'none'),
		},
	];
}

/** Décomptes des personnes avec et sans chaque identifiant et chaque élément à confirmer, servis par la facette `/api/persons/facets` sous la même clé. */
export const PERSON_PRESENCE_FACETS = [...Object.keys(IDENTIFIER_PARAMS), ...Object.keys(PENDING_PARAMS)];
