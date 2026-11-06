/**
 * Registre des filtres des publications, partagé par les vues de la liste des publications (notices, tableau, statistiques).
 *
 * Le contexte fixe le filtre de son entité. Il active les filtres propres à l'entité : le statut HAL pour un laboratoire, la position d'auteur pour un laboratoire ou une personne.
 */
import type { FilterGroup, ListFilter } from '#lib/filterRegistry.js';
import { SOURCE_ITEMS } from '#lib/filterItems.js';
import { docTypeFamilies, docTypePluralLabels } from '#lib/docTypes.svelte.js';
import { filterLabels, oaLabelsMap } from '#lib/labels.js';
import { contextEntityId, type PublicationListContext } from '#lib/publicationListContext.js';
import { yearsFilter } from '#lib/sharedFilters.js';

/** Rubriques du panneau des filtres des publications, dans l'ordre d'affichage. */
export const PUBLICATION_FILTER_GROUPS: readonly FilterGroup[] = [
	{ key: 'document', label: 'Document' },
	{ key: 'venue', label: 'Revue et éditeur' },
	{ key: 'authors', label: 'Auteurs' },
	{ key: 'content', label: 'Sujets et citations' },
	{ key: 'access', label: 'Accès' },
	{ key: 'collaborations', label: 'Collaborations' },
	{ key: 'sources', label: 'Sources' },
];

/**
 * Filtre des laboratoires des publications, avec l'option « Aucun labo » (`none`, ajoutée aux décomptes par `usePublicationFacets`). `fixed` renvoie le laboratoire imposé par la page.
 *
 * « Aucun labo » exclut les laboratoires : la cocher décoche les laboratoires, cocher un laboratoire la décoche. Une case cochée s'ajoute à la fin de la sélection : la dernière valeur est celle qui vient d'être cochée.
 */
export function labsFilter(group: string, fixed: () => string | null): ListFilter {
	return {
		key: 'labs',
		control: 'checkbox',
		label: filterLabels.labs,
		param: 'lab_id',
		group,
		facet: { type: 'labeled', apiKey: 'labs' },
		searchable: true,
		fixed,
		normalize: (selected) => (selected.at(-1) === 'none' ? ['none'] : selected.filter((v) => v !== 'none')),
	};
}

/** Filtres des publications dans le contexte, dans l'ordre d'affichage au sein de chaque rubrique. */
export function publicationFilters(context: PublicationListContext): ListFilter[] {
	return [
		{
			key: 'docTypes',
			control: 'checkbox',
			label: filterLabels.types,
			param: 'doc_type',
			group: 'document',
			facet: { type: 'label_map', apiKey: 'doc_types', labels: docTypePluralLabels() },
			groups: docTypeFamilies().map((f) => ({ label: f.label, values: f.types })),
			showColumns: ['type'],
		},
		yearsFilter('document'),
		{
			key: 'languages',
			control: 'checkbox',
			label: 'Langues',
			param: 'language',
			group: 'document',
			facet: { type: 'labeled', apiKey: 'languages' },
			searchable: true,
		},
		{
			key: 'doiAgency',
			control: 'checkbox',
			label: 'DOI',
			param: 'doi_agency',
			group: 'document',
			facet: { type: 'labeled', apiKey: 'doi_agencies' },
			tooltip: "Agence d'enregistrement du DOI",
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
		labsFilter('authors', () => contextEntityId(context, 'lab')),
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
			key: 'partner',
			control: 'entity',
			label: filterLabels.partner,
			param: 'partner_ror',
			group: 'collaborations',
			entity: 'partner',
		},
		{
			key: 'countries',
			control: 'checkbox',
			label: filterLabels.countries,
			param: 'country',
			group: 'collaborations',
			facet: {
				type: 'labeled',
				apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.label} (${c.value.toUpperCase()})`, count: c.count }),
			},
			searchable: true,
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
