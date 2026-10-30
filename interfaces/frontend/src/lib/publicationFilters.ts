/**
 * Registre des filtres des publications, partagé par la liste des publications et la page Statistiques.
 *
 * Le contexte fixe le filtre de son entité. Il active les filtres propres à l'entité : le statut HAL pour un laboratoire, la correspondance et le périmètre pour une personne.
 */
import { ALL_TOKEN, explicitSelectionUrl, type ListFilter } from '#lib/filterRegistry.js';
import { SOURCE_ITEMS } from '#lib/filterItems.js';
import { institution } from '#lib/institution.svelte.js';
import { docTypeFamilies, docTypePluralLabels } from '#lib/docTypes.svelte.js';
import { filterLabels, oaLabelsMap } from '#lib/labels.js';
import { contextEntityId, type PublicationListContext } from '#lib/publicationListContext.js';

/** Filtres des publications dans le contexte, dans l'ordre d'affichage. Un filtre sans `group` figure dans la barre principale. `defaultDocTypes` : types que la page sélectionne quand l'URL ne fixe pas les types, et que son URL omet. */
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
			facet: { type: 'simple', apiKey: 'years' },
			// Un lien vers la page Statistiques écrit `all` : elle applique alors ses années par défaut seulement à l'ouverture sans paramètre `year`.
			url: explicitSelectionUrl(ALL_TOKEN),
		},
		{
			key: 'languages',
			control: 'checkbox',
			label: 'Langues',
			param: 'language',
			facet: { type: 'labeled', apiKey: 'languages' },
			searchable: true,
		},
		{
			key: 'serial',
			control: 'entity',
			label: filterLabels.serial,
			param: 'serial_id',
			entity: 'serial',
			fixed: () => contextEntityId(context, 'serial'),
			showColumns: ['serial'],
		},
		{
			key: 'author',
			control: 'entity',
			label: filterLabels.author,
			param: 'author_id',
			entity: 'person',
		},
		{
			key: 'labs',
			control: 'checkbox',
			label: filterLabels.labs,
			param: 'lab_id',
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
			key: 'access',
			control: 'checkbox',
			label: filterLabels.access,
			param: 'access',
			facet: { type: 'labeled', apiKey: 'access' },
		},
		{
			key: 'halStatus',
			control: 'checkbox',
			label: 'Statuts HAL',
			param: 'hal_status',
			facet: { type: 'labeled', apiKey: 'hal_status' },
			enabled: () => context.kind === 'lab',
			showColumns: ['hal_status'],
		},
		{
			key: 'publisher',
			control: 'entity',
			label: filterLabels.publisher,
			param: 'publisher_id',
			entity: 'publisher',
			group: 'Revue et éditeur',
			fixed: () => contextEntityId(context, 'publisher'),
			showColumns: ['serial'],
		},
		{
			key: 'apc',
			control: 'checkbox',
			label: filterLabels.apc,
			param: 'has_apc',
			facet: { type: 'labeled', apiKey: 'apc' },
			group: 'Revue et éditeur',
			tooltip: "Pas d'info après 2024\nSans APC = ou APC non documentés",
			showColumns: ['apc'],
		},
		{
			key: 'oa',
			control: 'checkbox',
			label: filterLabels.oaStatuses,
			param: 'oa_status',
			facet: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			group: 'Revue et éditeur',
			showColumns: ['oa_status'],
		},
		{
			key: 'license',
			control: 'checkbox',
			label: filterLabels.licenses,
			param: 'license',
			facet: { type: 'labeled', apiKey: 'licenses' },
			group: 'Revue et éditeur',
			tooltip: 'Licence de la version éditeur',
			showColumns: ['license'],
		},
		{
			key: 'corresponding',
			control: 'checkbox',
			label: 'Auteur correspondant',
			param: 'is_corresponding',
			facet: { type: 'label_map', apiKey: 'corresponding', labels: { yes: 'Oui', no: 'Non' } },
			group: 'Auteurs',
			enabled: () => context.kind === 'person',
			hideWhenEmpty: true,
			showColumns: ['corr'],
		},
		{
			key: 'perimeter',
			control: 'checkbox',
			get label() {
				return institution.name;
			},
			param: 'in_perimeter',
			facet: { type: 'labeled', apiKey: 'in_perimeter' },
			group: 'Auteurs',
			enabled: () => context.kind === 'person',
			hideWhenEmpty: true,
		},
		{
			key: 'partner',
			control: 'entity',
			label: filterLabels.partner,
			param: 'partner_ror',
			entity: 'partner',
			group: 'Auteurs',
		},
		{
			key: 'countries',
			control: 'checkbox',
			label: filterLabels.countries,
			param: 'country',
			facet: {
				type: 'labeled',
				apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.label} (${c.value.toUpperCase()})`, count: c.count }),
			},
			group: 'Auteurs',
			searchable: true,
		},
		{
			key: 'subjects',
			control: 'entity',
			label: 'Sujets',
			param: 'subject_id',
			entity: 'subject',
			multiple: true,
			group: 'Détails',
			fixed: () => contextEntityId(context, 'subject'),
		},
		{
			key: 'doiAgency',
			control: 'checkbox',
			label: 'DOI',
			param: 'doi_agency',
			facet: { type: 'labeled', apiKey: 'doi_agencies' },
			group: 'Détails',
			tooltip: "Agence d'enregistrement du DOI",
		},
		{
			key: 'sources',
			control: 'presence',
			label: filterLabels.sources,
			param: 'source_filter',
			group: 'Détails',
			items: SOURCE_ITEMS,
			showColumns: ['sources'],
		},
	];
}
