/**
 * Registre des filtres des publications, partagé par la liste des publications et la page Statistiques.
 *
 * Le contexte fixe le filtre de son entité. Il active les filtres propres à l'entité : le statut HAL pour un laboratoire, le périmètre pour une personne, la position d'auteur pour l'un et l'autre.
 */
import { ALL_TOKEN, explicitSelectionUrl, type FilterGroup, type ListFilter } from '#lib/filterRegistry.js';
import { SOURCE_ITEMS } from '#lib/filterItems.js';
import { docTypeFamilies, docTypePluralLabels } from '#lib/docTypes.svelte.js';
import { filterLabels, oaLabelsMap } from '#lib/labels.js';
import { contextEntityId, type PublicationListContext } from '#lib/publicationListContext.js';

/** Rubriques du panneau des filtres des publications, dans l'ordre d'affichage. */
export const PUBLICATION_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'publication', label: 'Publication' },
	{ key: 'access', label: 'Accès ouvert' },
	{ key: 'affiliations', label: 'Affiliations' },
	{ key: 'venue', label: 'Revue et éditeur' },
	{ key: 'authors', label: 'Auteurs' },
	{ key: 'content', label: 'Sujets et citations' },
	{ key: 'sources', label: 'Sources' },
];

/** Filtres des publications dans le contexte, dans l'ordre d'affichage au sein de chaque rubrique. `defaultDocTypes` : types que la page sélectionne quand l'URL ne fixe pas les types, et que son URL omet. */
export function publicationFilters(
	context: PublicationListContext,
	defaultDocTypes: readonly string[] = [],
): ListFilter[] {
	return [
		{
			key: 'docTypes',
			control: 'checkbox',
			label: filterLabels.types,
			param: 'doc_type',
			group: 'publication',
			facet: { type: 'label_map', apiKey: 'doc_types', labels: docTypePluralLabels() },
			groups: docTypeFamilies().map((f) => ({ label: f.label, values: f.types })),
			showColumns: ['type'],
			url: explicitSelectionUrl(defaultDocTypes.length ? defaultDocTypes.join(',') : ALL_TOKEN),
		},
		{
			key: 'years',
			control: 'checkbox',
			label: filterLabels.years,
			param: 'year',
			group: 'publication',
			facet: { type: 'simple', apiKey: 'years' },
			range: true,
			// Un lien vers la page Statistiques écrit `all` : elle applique alors ses années par défaut seulement à l'ouverture sans paramètre `year`.
			url: explicitSelectionUrl(ALL_TOKEN),
		},
		{
			key: 'languages',
			control: 'checkbox',
			label: 'Langues',
			param: 'language',
			group: 'publication',
			facet: { type: 'labeled', apiKey: 'languages' },
			searchable: true,
		},
		{
			key: 'doiAgency',
			control: 'checkbox',
			label: 'DOI',
			param: 'doi_agency',
			group: 'publication',
			facet: { type: 'labeled', apiKey: 'doi_agencies' },
			tooltip: "Agence d'enregistrement du DOI",
		},
		{
			key: 'access',
			control: 'checkbox',
			label: filterLabels.access,
			param: 'access',
			group: 'access',
			facet: { type: 'labeled', apiKey: 'access' },
		},
		{
			key: 'oa',
			control: 'checkbox',
			label: filterLabels.oaStatuses,
			param: 'oa_status',
			group: 'access',
			facet: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			showColumns: ['oa_status'],
		},
		{
			key: 'license',
			control: 'checkbox',
			label: filterLabels.licenses,
			param: 'license',
			group: 'access',
			facet: { type: 'labeled', apiKey: 'licenses' },
			tooltip: 'Licence de la version éditeur',
			showColumns: ['license'],
		},
		{
			key: 'labs',
			control: 'checkbox',
			label: filterLabels.labs,
			param: 'lab_id',
			group: 'affiliations',
			facet: { type: 'labeled', apiKey: 'labs' },
			searchable: true,
			fixed: () => contextEntityId(context, 'lab'),
			// « Aucun labo » ne se combine pas avec un laboratoire.
			normalize: (selected) =>
				selected.includes('none') && selected.length > 1
					? selected.filter((v) => v !== 'none')
					: selected,
		},
		{
			key: 'partner',
			control: 'entity',
			label: filterLabels.partner,
			param: 'partner_ror',
			group: 'affiliations',
			entity: 'partner',
		},
		{
			key: 'countries',
			control: 'checkbox',
			label: filterLabels.countries,
			param: 'country',
			group: 'affiliations',
			facet: {
				type: 'labeled',
				apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.label} (${c.value.toUpperCase()})`, count: c.count }),
			},
			searchable: true,
		},
		{
			key: 'serial',
			control: 'entity',
			label: filterLabels.serial,
			param: 'serial_id',
			group: 'venue',
			entity: 'serial',
			fixed: () => contextEntityId(context, 'serial'),
			showColumns: ['serial'],
		},
		{
			key: 'publisher',
			control: 'entity',
			label: filterLabels.publisher,
			param: 'publisher_id',
			group: 'venue',
			entity: 'publisher',
			fixed: () => contextEntityId(context, 'publisher'),
			showColumns: ['serial'],
		},
		{
			key: 'author',
			control: 'entity',
			label: filterLabels.author,
			param: 'author_id',
			group: 'authors',
			entity: 'person',
		},
		{
			key: 'authorPosition',
			control: 'checkbox',
			label: 'Position auteur',
			param: 'author_position',
			group: 'authors',
			facet: {
				type: 'label_map',
				apiKey: 'author_positions',
				labels: {
					corresponding: 'Correspondant',
					first: 'Premier',
					last: 'Dernier',
					other: 'Autre',
				},
			},
			enabled: () => context.kind === 'person' || context.kind === 'lab',
			showColumns: ['corr'],
		},
		{
			key: 'perimeter',
			control: 'checkbox',
			label: 'Affiliations',
			param: 'in_perimeter',
			group: 'authors',
			facet: { type: 'labeled', apiKey: 'in_perimeter' },
			enabled: () => context.kind === 'person',
		},
		{
			key: 'subjects',
			control: 'entity',
			label: 'Sujets',
			param: 'subject',
			group: 'content',
			entity: 'subject',
			multiple: true,
			fixed: () => contextEntityId(context, 'subject'),
		},
		{
			key: 'citationTops',
			control: 'checkbox',
			label: filterLabels.citationTops,
			param: 'citation_top',
			group: 'content',
			facet: { type: 'labeled', apiKey: 'citation_tops' },
			tooltip: "D'après OpenAlex. Le top 10 % comprend le top 1 %",
			showColumns: ['citation_top'],
		},
		{
			key: 'sources',
			control: 'presence',
			label: filterLabels.sources,
			param: 'source_filter',
			group: 'sources',
			items: SOURCE_ITEMS,
			showColumns: ['sources'],
		},
		{
			key: 'halStatus',
			control: 'checkbox',
			label: 'Statut HAL',
			param: 'hal_status',
			group: 'sources',
			facet: { type: 'labeled', apiKey: 'hal_status' },
			enabled: () => context.kind === 'lab',
			showColumns: ['hal_status'],
		},
	];
}
