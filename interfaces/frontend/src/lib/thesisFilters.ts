/**
 * Registre des filtres de la liste des thèses. Les thèses sont des publications : elles se filtrent et se décomptent par les routes des publications.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';
import { labsFilter } from '#lib/publicationFilters.js';

/** Types de document des thèses, soutenues ou en cours. Sans filtre de statut, la liste retient les deux. */
export const THESIS_DOC_TYPES = 'thesis,ongoing_thesis';

/** Rubriques du panneau des filtres des thèses, dans l'ordre d'affichage. */
export const THESIS_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'document', label: 'Thèse' },
	{ key: 'affiliations', label: 'Affiliations' },
	{ key: 'access', label: 'Accès' },
	{ key: 'sources', label: 'Sources' },
];

/** Filtres des thèses. `labId` : laboratoire imposé par la page (onglet Thèses d'un laboratoire). */
export function thesisFilters(labId?: number): ListFilter[] {
	return [
		{
			key: 'status',
			control: 'checkbox',
			label: 'Statuts',
			param: 'doc_type',
			group: 'document',
			facet: {
				type: 'label_map',
				apiKey: 'doc_types',
				labels: { thesis: 'Soutenues', ongoing_thesis: 'En cours' },
				onlyLabeled: true,
			},
		},
		{
			key: 'years',
			control: 'checkbox',
			label: filterLabels.years,
			param: 'year',
			group: 'document',
			facet: { type: 'simple', apiKey: 'years' },
			range: true,
		},
		labsFilter('affiliations', () => (labId == null ? null : String(labId))),
		{
			key: 'access',
			control: 'checkbox',
			label: filterLabels.access,
			param: 'access',
			group: 'access',
			facet: { type: 'labeled', apiKey: 'access' },
		},
		{
			key: 'sources',
			control: 'presence',
			label: filterLabels.sources,
			param: 'source_filter',
			group: 'sources',
			items: [
				{ key: 'hal', label: 'HAL' },
				{ key: 'openalex', label: 'OpenAlex' },
				{ key: 'scanr', label: 'ScanR' },
				{ key: 'theses', label: 'theses.fr' },
			],
		},
	];
}
