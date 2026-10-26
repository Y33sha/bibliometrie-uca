<script lang="ts">
	import AccessButton from '#lib/components/AccessButton.svelte';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import ResultCount from '#lib/components/ResultCount.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { institution } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { asset, resolve } from '$app/paths';
	import { withBase } from '#lib/paths.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import EntityFilter from '#lib/components/EntityFilter.svelte';
	import PresenceFilterToggle from '#lib/components/PresenceFilterToggle.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import { SOURCE_ITEMS } from '#lib/filterItems.js';
	import {
		activeColumns,
		appendFilterParams,
		clearValue,
		facetDefs,
		filterSections,
		initialValues,
		isActive,
		isAvailable,
		isShown,
		restoreValues,
		urlFilterDefs,
		urlState,
		type CheckboxFilter,
		type EntityChoiceFilter,
		type ListFilter,
	} from '#lib/filterRegistry.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import { oaLabelsMap, oaStatusLabel } from '#lib/labels.js';
	import { licenseLabels } from '#lib/licenses.js';
	import {
		docTypePlural,
		docTypeFamilies,
		publicationsDocTypes,
		docTypeFilterToken,
		docTypeFilterFromToken,
	} from '#lib/labels.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { useColumnVisibility } from '#lib/composables/useColumnVisibility.svelte.js';
	import ColumnMenu from '#lib/components/ColumnMenu.svelte';
	import { paramsToQuery } from '#lib/utils.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import IconButton from '#lib/components/IconButton.svelte';

	import type { components } from '#lib/api/schema.js';
	type Publication = components['schemas']['PublicationListItem'] & {
		// Champs présents quand l'API est appelée avec `person_id` (cf. routes /api/publications côté backend qui enrichit la réponse). Optionnels car non garantis hors contexte personne.
		is_corresponding?: boolean | null;
		contribution_id?: number | null;
		hal_collections?: string[] | null;
	};

	// --- Props ---
	// Composant de liste de publications réutilisable. Utilisé par :
	// - `/publications` (mode autonome avec sync URL ; en session admin, une icône ouvre le volet de la publication)
	// - `/subjects/[id]?tab=publications` (filtre `subject_id` fixe)
	// - `/structures/[id]?tab=publications` (filtre `lab_id` fixe + colonne Statut HAL)
	// - `/persons/[id]?tab=publications` (filtre `person_id` + facets Corresp./Périmètre)
	// - `/journals/[id]?tab=publications` (filtre `serial_id` fixe)
	// - `/publishers/[id]?tab=publications` (filtre `publisher_id` fixe)
	// - `/monographs/[id]` (filtre `monograph_id` fixe)
	interface ExternalFilters {
		subjectId?: number;
		subjectLabel?: string;
		labId?: number;
		labLabel?: string;
		/** Collection HAL du laboratoire (ex 'lmbp'). Requis pour calculer la colonne « Statut HAL ». */
		halCollection?: string;
		personId?: number;
		personLabel?: string;
		serialId?: number;
		publisherId?: number;
		monographId?: number;
	}
	type ApcMode = 'institution' | 'person';
	let {
		apiKey = 'publication-list',
		externalFilters,
		urlSync = true,
		basePath = '/publications',
		showFilterBanner = true,
		showHalStatusColumn = false,
		showCorrespondingColumn = false,
		showPerimeterFacet = false,
		showAdminExclude = false,
		apcMode = 'institution' as ApcMode,
		perPage = 100,
		restrictToPublications = false,
		onExcludeContribution,
		onopenPublication,
		activePublicationId = null,
	}: {
		apiKey?: string;
		externalFilters?: ExternalFilters;
		urlSync?: boolean;
		basePath?: string;
		showFilterBanner?: boolean;
		/** Affiche la colonne et la facet « Statut HAL ». Requiert `externalFilters.halCollection` pour le calcul du badge. */
		showHalStatusColumn?: boolean;
		/** Affiche la colonne et la facet « Auteur correspondant ». */
		showCorrespondingColumn?: boolean;
		/** Affiche la facet du périmètre de l'établissement (in_perimeter). */
		showPerimeterFacet?: boolean;
		/** Affiche la 1ère colonne avec un bouton ✕ pour exclure la contribution. Le parent gère l'auth check et passe le callback. Si le callback retourne `true` (ou void), la ligne est retirée du tableau ; retourne `false` pour annuler (ex. l'utilisatrice a cliqué Annuler dans un confirm). */
		showAdminExclude?: boolean;
		/** Mode de rendu du tag APC :
		 *  - 'institution' : paiements sur un budget du périmètre de l'établissement (défaut)
		 *  - 'person' : 'institution' + classe `apc-other` si !is_corresponding */
		apcMode?: ApcMode;
		/** Nombre d'éléments par page (50 pour les onglets, 100 pour /publications). */
		perPage?: number;
		/** Par défaut, restreint la liste à la famille « Publications » (au sens strict) tant qu'aucun type n'est coché. Réservé à la liste générale ; les listes embarquées (journal, éditeur, personne…) restent permissives. L'utilisatrice élargit via la facet « Types ». */
		restrictToPublications?: boolean;
		onExcludeContribution?: (contributionId: number, publicationId: number) => void | boolean | Promise<void | boolean>;
		/** Ouvre le volet de la publication dans la page hôte. Fourni, il ajoute en tête de ligne une icône qui l'appelle ; le titre mène toujours à la fiche. */
		onopenPublication?: (publicationId: number) => void;
		/** Publication ouverte par la page hôte, dont la ligne est mise en évidence. */
		activePublicationId?: number | null;
	} = $props();

	const hasFixedLab = $derived(externalFilters?.labId != null);
	const hasFixedPerson = $derived(externalFilters?.personId != null);

	type HalStatus = 'ok' | 'notice' | 'hors_collection' | 'hors_hal';
	const HAL_STATUS_META: Record<HalStatus, { label: string; css: string }> = {
		ok:              { label: 'OK',              css: 'hal-ok' },
		notice:          { label: 'Notice',          css: 'hal-notice' },
		hors_collection: { label: 'Hors collection', css: 'hal-hors-collection' },
		hors_hal:        { label: 'Hors HAL',        css: 'hal-hors-hal' },
	};
	function computeHalStatus(p: Publication): HalStatus {
		if (!p.hal_id) return 'hors_hal';
		const labCol = externalFilters?.halCollection;
		if (!labCol || !p.hal_collections || !p.hal_collections.includes(labCol)) return 'hors_collection';
		if (!p.oa_status || ['closed', 'unknown'].includes(p.oa_status)) return 'notice';
		return 'ok';
	}

	// --- Column visibility ---
	// Ordre des colonnes = ordre dans le tableau. Les colonnes optionnelles (hal_status, corr) ne sont incluses dans la liste que si la prop correspondante est activée — sinon l'utilisatrice n'a pas à les voir dans le menu de visibilité.
	const columnDefs = [
		{ key: 'type',       label: 'Type' },
		{ key: 'year',       label: 'Année' },
		{ key: 'doi',        label: 'DOI' },
		{ key: 'title',      label: 'Titre',      fixed: true },
		{ key: 'serial',    label: 'Revue' },
		{ key: 'publisher',  label: 'Éditeur' },
		// svelte-ignore state_referenced_locally
		...(hasFixedLab ? [] : [{ key: 'labs', label: 'Labo(s)' }]),
		// svelte-ignore state_referenced_locally
		...(showCorrespondingColumn ? [{ key: 'corr', label: 'Corresp.' }] : []),
		{ key: 'apc',        label: 'APC' },
		{ key: 'oa_status',  label: 'Voie OA' },
		{ key: 'license',    label: 'Licence' },
		// svelte-ignore state_referenced_locally
		...(showHalStatusColumn ? [{ key: 'hal_status', label: 'Statut HAL' }] : []),
		{ key: 'sources',    label: 'Sources' },
		{ key: 'access',     label: 'Accès',      fixed: true },
	];
	const initialHidden = ['apc', 'oa_status', 'license', 'publisher', 'sources'];
	// Libellés de la colonne Licence, servis par l'API.
	let licenseNames = $state<Record<string, string>>({});
	// svelte-ignore state_referenced_locally
	if (showHalStatusColumn) initialHidden.push('hal_status');
	const cv = useColumnVisibility(columnDefs, initialHidden);
	const col = cv.col;

	// --- Filtres ---
	let search = $state('');
	let currentSort = $state('year_desc');

	const fixedId = (id: number | undefined): string | null => (id != null ? String(id) : null);

	// Ordre du tableau = ordre d'affichage. Un filtre sans `group` figure dans la barre principale.
	const FILTERS: ListFilter[] = [
		{
			key: 'docTypes',
			control: 'checkbox',
			label: 'Types',
			param: 'doc_type',
			facet: { type: 'label_map', apiKey: 'doc_types', labels: docTypePlural },
			groups: docTypeFamilies.map((f) => ({ label: f.label, values: f.types })),
			showColumns: ['type'],
			url: {
				encode: docTypeFilterToken,
				decode: docTypeFilterFromToken,
				defaultValue: publicationsDocTypes.join(','),
			},
		},
		{
			key: 'years',
			control: 'checkbox',
			label: 'Années',
			param: 'year',
			facet: { type: 'simple', apiKey: 'years' },
		},
		{
			key: 'labs',
			control: 'checkbox',
			label: 'Laboratoires',
			param: 'lab_id',
			facet: { type: 'labeled', apiKey: 'labs' },
			searchable: true,
			fixed: () => fixedId(externalFilters?.labId),
			// « Aucun labo » ne se combine pas avec un laboratoire.
			normalize: (selected) =>
				selected.includes('none') && selected.length > 1
					? selected.filter((v) => v !== 'none')
					: selected,
		},
		{
			key: 'access',
			control: 'checkbox',
			label: 'Accès',
			param: 'access',
			facet: { type: 'labeled', apiKey: 'access' },
		},
		{
			key: 'halStatus',
			control: 'checkbox',
			label: 'Statut HAL',
			param: 'hal_status',
			facet: { type: 'labeled', apiKey: 'hal_status' },
			enabled: () => showHalStatusColumn,
			showColumns: ['hal_status'],
		},
		{
			key: 'serial',
			control: 'entity',
			label: 'Revue',
			param: 'serial_id',
			entity: 'serial',
			group: 'Revue et éditeur',
			fixed: () => fixedId(externalFilters?.serialId),
			showColumns: ['serial'],
		},
		{
			key: 'publisher',
			control: 'entity',
			label: 'Éditeur',
			param: 'publisher_id',
			entity: 'publisher',
			group: 'Revue et éditeur',
			fixed: () => fixedId(externalFilters?.publisherId),
			showColumns: ['serial'],
		},
		{
			key: 'apc',
			control: 'checkbox',
			label: 'APC',
			param: 'has_apc',
			facet: { type: 'labeled', apiKey: 'apc' },
			group: 'Revue et éditeur',
			tooltip: "Pas d'info après 2024\nSans APC = ou APC non documentés",
			showColumns: ['apc'],
		},
		{
			key: 'oa',
			control: 'checkbox',
			label: 'Voies OA',
			param: 'oa_status',
			facet: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			group: 'Revue et éditeur',
			showColumns: ['oa_status'],
		},
		{
			key: 'license',
			control: 'checkbox',
			label: 'Licence',
			param: 'license',
			facet: { type: 'labeled', apiKey: 'licenses' },
			group: 'Revue et éditeur',
			tooltip: 'Licence de la version éditeur',
			showColumns: ['license'],
		},
		{
			key: 'author',
			control: 'entity',
			label: 'Auteur',
			param: 'author_id',
			entity: 'person',
			group: 'Auteurs',
		},
		{
			key: 'corresponding',
			control: 'checkbox',
			label: 'Corresp.',
			param: 'is_corresponding',
			facet: { type: 'label_map', apiKey: 'corresponding', labels: { yes: 'Oui', no: 'Non' } },
			group: 'Auteurs',
			enabled: () => showCorrespondingColumn,
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
			enabled: () => showPerimeterFacet,
			hideWhenEmpty: true,
		},
		{
			key: 'partner',
			control: 'entity',
			label: 'Organisation partenaire',
			param: 'partner_ror',
			entity: 'partner',
			group: 'Auteurs',
		},
		{
			key: 'countries',
			control: 'checkbox',
			label: 'Pays',
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
			key: 'languages',
			control: 'checkbox',
			label: 'Langues',
			param: 'language',
			facet: { type: 'labeled', apiKey: 'languages' },
			group: 'Détails',
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
			fixed: () => fixedId(externalFilters?.subjectId),
		},
		{
			key: 'sources',
			control: 'presence',
			label: 'Sources',
			param: 'source_filter',
			group: 'Détails',
			items: SOURCE_ITEMS,
			showColumns: ['sources'],
		},
	];
	const sections = filterSections(FILTERS);

	let values = $state(initialValues(FILTERS));
	let showMoreFilters = $state(false);
	const moreFiltersActive = $derived(
		sections.groups.flatMap((g) => g.filters).filter((f) => isAvailable(f) && isActive(f, values)).length,
	);

	// Le bandeau ne signale que le sujet, contexte fixé par la route (sans facette propre ici).
	const subjectBannerText = $derived(
		externalFilters?.subjectId
			? 'sujet = ' + (externalFilters.subjectLabel ?? `#${externalFilters.subjectId}`)
			: '',
	);

	// Lien vers le tableau de bord, pendant inverse du bouton « Voir les publications ». Transmet les filtres que le tableau de bord sait représenter (les facettes propres à la liste — accès, pays, sources, statut HAL, correspondance, périmètre — n'y ont pas d'équivalent). Masqué quand la route fixe une dimension hors de sa portée (personne, sujet).
	const showStatsLink = $derived(!externalFilters?.personId && !externalFilters?.subjectId && !externalFilters?.monographId);
	const statsUrl = $derived.by(() => {
		const p = new URLSearchParams();
		const { checkbox, entity } = values;
		if (checkbox.years.length) p.set('year', checkbox.years.join(','));
		p.set('doc_type', docTypeFilterToken(checkbox.docTypes));
		if (checkbox.oa.length) p.set('oa_status', checkbox.oa.join(','));
		if (checkbox.license.length) p.set('license', checkbox.license.join(','));
		if (checkbox.apc.length) p.set('has_apc', checkbox.apc.join(','));
		// Laboratoire : fixé par la route ou choisi en facette (« aucun labo » n'a pas de sens côté stats).
		const labId =
			externalFilters?.labId != null
				? String(externalFilters.labId)
				: checkbox.labs.filter((v) => v !== 'none').join(',');
		if (labId) p.set('lab_id', labId);
		// Éditeur / revue : fixés par la route ou choisis en facette.
		const publisherId = fixedId(externalFilters?.publisherId) ?? entity.publisher.join(',');
		if (publisherId) p.set('publisher_id', publisherId);
		const serialId = fixedId(externalFilters?.serialId) ?? entity.serial.join(',');
		if (serialId) p.set('serial_id', serialId);
		if (entity.partner.length) p.set('partner_ror', entity.partner.join(','));
		return resolve('stats') + '?' + paramsToQuery(p);
	});

	// Sort display
	const yearSort = $derived(sortDirection(currentSort, 'year'));
	const titleSort = $derived(sortDirection(currentSort, 'title'));
	const apcSort = $derived(sortDirection(currentSort, 'apc'));

	// --- Shared filter params builder ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('excluded_doc_type', 'ongoing_thesis');
		if (externalFilters?.personId != null) params.set('person_id', String(externalFilters.personId));
		if (externalFilters?.monographId != null) params.set('monograph_id', String(externalFilters.monographId));
		appendFilterParams(FILTERS, values, params);
		return params;
	}

	// --- Composables ---
	const listing = usePaginatedFetch<Publication>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/publications/facets',
		apiKey: () => `${apiKey}-facets`,
		// Inclut le terme de recherche pour que les comptes de facettes suivent le champ de recherche (comme la liste), pas seulement les autres filtres.
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
		sourceCountsKey: 'source_counts',
		facets: facetDefs(FILTERS),
		afterLoad(data, options) {
			options.labs = [
				{ value: 'none', text: '— Aucun labo —', count: (data.no_lab_count as number) ?? 0 },
				...options.labs,
			];
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			...urlFilterDefs(FILTERS),
			search:      { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'year_desc' },
			currentPage: { type: 'page',   urlKey: 'page' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			...urlState(FILTERS, values),
			search,
			currentSort,
			currentPage: listing.page,
		}));
	}

	function onFilterChange() {
		listing.page = 1;
		syncUrl();
		listing.load();
		facets.load();
	}

	function onCheckboxChange(filter: CheckboxFilter, selected: string[]) {
		values.checkbox[filter.key] = filter.normalize ? filter.normalize(selected) : selected;
		onFilterChange();
	}

	function onEntityChange(filter: EntityChoiceFilter, ids: string[]) {
		values.entity[filter.key] = ids;
		onFilterChange();
	}

	function clearFilter(filter: ListFilter) {
		clearValue(filter, values);
		onFilterChange();
	}

	function clearAllFilters() {
		for (const f of FILTERS) clearValue(f, values);
		onFilterChange();
	}

	const optionCount = (key: string): number => facets.options[key]?.length ?? 0;

	const onSearchInput = url.debouncedSearch(() => {
		listing.page = 1;
		syncUrl();
		listing.load();
		facets.load();
	});

	function toggleSort(column: 'year' | 'title' | 'apc') {
		currentSort = nextSort(currentSort, column, column === 'title' ? 'asc' : 'desc');
		onFilterChange();
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		const q = search.trim();
		if (q) params.set('search', q);
		// Colonnes visibles → le CSV reflète le tableau affiché.
		params.set('columns', cv.visibleColumns.join(','));
		return withBase(`/api/publications/export.csv?${paramsToQuery(params)}`);
	}

	async function onExcludeClick(p: Publication) {
		if (!onExcludeContribution || p.contribution_id == null) return;
		const result = await onExcludeContribution(p.contribution_id, p.id);
		// `false` = annulé par le parent (ex. l'utilisatrice a cliqué Annuler) ; `true` ou `undefined` = succès → on retire la ligne du tableau.
		if (result === false) return;
		listing.items = listing.items.filter((item) => item.id !== p.id);
	}

	onMount(async () => {
		licenseLabels()
			.then((labels) => (licenseNames = labels))
			.catch(() => {});
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			restoreValues(FILTERS, restored, values);
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) listing.page = restored.currentPage as number;
		}

		// Défaut « Publications » (liste générale uniquement) : sans filtre de type explicite dans l'URL, on pré-sélectionne la famille Publications. La sélection est réelle (et non un filtre caché), donc la facet « Types » la reflète ; cocher d'autres types ou « Tous » l'élargit. Le token `all` dans l'URL (« Tous » explicite) laisse la sélection vide.
		if (restrictToPublications && !(urlSync && page.url.searchParams.has('doc_type'))) {
			values.checkbox.docTypes = [...publicationsDocTypes];
		}

		// Forcer l'affichage des colonnes liées aux filtres actifs
		const needed = activeColumns(FILTERS, values);
		if (needed.length) cv.ensure(needed);

		await facets.load();
		listing.load();
	});
</script>

{#if showFilterBanner && subjectBannerText}
	<div class="info-box">Filtre actif : {subjectBannerText}</div>
{/if}

<div class="toolbar-card toolbar-sticky publication-toolbar">
	<div class="toolbar publication-toolbar-main">
		<input type="search" class="publication-search" placeholder="Rechercher par titre ou sujet..." bind:value={search} onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
		<ResultCount list={listing} one="publication" many="publications" />
		<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
		{#if showStatsLink}<a href={statsUrl} class="toolbar-action">Statistiques &rarr;</a>{/if}
	</div>
	<div class="toolbar publication-toolbar-facets">
		<span class="facets-label">Filtrer par&nbsp;:</span>
		{#each sections.primary as f (f.key)}
			{#if isShown(f, optionCount)}{@render filterControl(f)}{/if}
		{/each}
		<button type="button" class="more-filters-btn" class:open={showMoreFilters} aria-expanded={showMoreFilters} onclick={() => (showMoreFilters = !showMoreFilters)}>
			{showMoreFilters ? 'Cacher les filtres' : 'Plus de filtres'}
			{#if moreFiltersActive > 0}<span class="facet-badge">{moreFiltersActive}</span>{/if}
			<span class="chevron" class:up={showMoreFilters} aria-hidden="true"></span>
		</button>
	</div>
	{#if showMoreFilters}
		<div class="more-filters">
			{#each sections.groups as g (g.label)}
				{@const shown = g.filters.filter((f) => isShown(f, optionCount))}
				{#if shown.length}
					<div class="filter-group" role="group" aria-label={g.label} title={g.label}>
						{#each shown as f (f.key)}{@render filterControl(f)}{/each}
					</div>
				{/if}
			{/each}
		</div>
	{/if}
	<ActiveFilterBar filters={FILTERS} {values} options={facets.options} onclear={clearFilter} onclearall={clearAllFilters} />
</div>

{#snippet filterControl(f: ListFilter)}
	{#if f.control === 'checkbox'}
		<FacetDropdown label={f.label} options={facets.options[f.key] ?? []} searchable={f.searchable} groups={f.groups} tooltip={f.tooltip} bind:selected={values.checkbox[f.key]} onchange={(selected) => onCheckboxChange(f, selected)} />
	{:else if f.control === 'entity'}
		<EntityFilter label={f.label} endpoint="/api/publications/facets" kind={f.entity} multiple={f.multiple} buildParams={buildFilterParams} selected={values.entity[f.key]} onchange={(ids) => onEntityChange(f, ids)} />
	{:else}
		<PresenceFilterToggle label={f.label} items={f.items} bind:states={values.presence[f.key]} counts={facets.sourceCounts} onchange={onFilterChange} />
	{/if}
{/snippet}

<div class="table-scroll">
<table class="data-table publication-table">
	<thead>
		<tr>
			{#if onopenPublication}<th style="width:28px"></th>{/if}
			{#if showAdminExclude}<th style="width:28px"></th>{/if}
			{#if col('type')}<th style="width:80px">Type</th>{/if}
			{#if col('year')}<th style="width:40px" class="sortable" class:active={yearSort !== null} onclick={() => toggleSort('year')}>
				An. <SortChevron direction={yearSort} />
			</th>{/if}
			{#if col('doi')}<th style="width:28px">DOI</th>{/if}
			<th class="sortable publication-col-title" class:active={titleSort !== null} onclick={() => toggleSort('title')}>
				Titre <SortChevron direction={titleSort} />
			</th>
			{#if col('serial')}<th class="publication-col-journal">Revue</th>{/if}
			{#if col('publisher')}<th class="publication-col-journal">Éditeur</th>{/if}
			{#if !hasFixedLab && col('labs')}<th style="width:80px">Labo(s)</th>{/if}
			{#if showCorrespondingColumn && col('corr')}<th style="width:30px" title="Auteur correspondant">&#9993;</th>{/if}
			{#if col('apc')}<th style="width:60px" class="sortable" class:active={apcSort !== null} onclick={() => toggleSort('apc')}>
				APC <SortChevron direction={apcSort} />
			</th>{/if}
			{#if col('oa_status')}<th style="width:60px">Voie OA</th>{/if}
			{#if col('license')}<th style="width:90px">Licence</th>{/if}
			{#if showHalStatusColumn && col('hal_status')}<th style="width:100px">Statut HAL</th>{/if}
			{#if col('sources')}<th style="width:100px">Sources</th>{/if}
			<th style="width:120px" class="col-menu-th">
				Accès
				<ColumnMenu columns={cv.columns} visibleColumns={cv.visibleColumns}
					showMenu={cv.showMenu}
					onToggle={cv.toggle}
					onClose={() => cv.showMenu = false}
					onOpen={() => cv.showMenu = !cv.showMenu} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#if listing.items.length === 0}
			<TableStatusRow loading={listing.loading} error={listing.error} colspan={cv.visibleColumns.length + (showAdminExclude ? 1 : 0) + (onopenPublication ? 1 : 0)} emptyText="Aucune publication trouvée" />
		{:else}
			{#each listing.items as p (p.id)}
				<tr class:active-row={p.id === activePublicationId}>
					{#if onopenPublication}
						<td class="row-actions">
							<IconButton icon="panel" label="Ouvrir le volet" onclick={() => onopenPublication(p.id)} />
						</td>
					{/if}
					{#if showAdminExclude}
						<td class="exclude-cell row-actions">
							{#if p.contribution_id != null}
								<button class="exclude-btn" title="Exclure ce lien auteur–publication"
									onclick={() => onExcludeClick(p)}>✕</button>
							{/if}
						</td>
					{/if}
					{#if col('type')}<td>
						{#if p.doc_type}<DocTypePill docType={p.doc_type} />{/if}
					</td>{/if}
					{#if col('year')}<td>{p.publication_year || ''}</td>{/if}
					{#if col('doi')}<td class="doi-cell">
						{#if p.doi}<DoiLink doi={p.doi} />{/if}
					</td>{/if}
					<td><a href={resolve(`publications/${p.id}`)} class="publication-title"><PublicationTitle titre={p.title} /></a></td>
					{#if col('serial')}<td class="journal-cell publication-col-journal">
						{#if p.serial_id}
							<a href={resolve(`journals/${p.serial_id}`)}>{p.serial}</a>
						{:else}
							{p.serial || ''}
						{/if}
					</td>{/if}
					{#if col('publisher')}<td class="journal-cell publication-col-journal">
						{#if p.publisher_id}
							<a href={resolve(`publishers/${p.publisher_id}`)}>{p.publisher}</a>
						{:else}
							{p.publisher || ''}
						{/if}
					</td>{/if}
					{#if !hasFixedLab && col('labs')}<td>
						{#each p.lab_items || [] as lab}
							<a href={resolve(`structures/${lab.id}`)} class="lab-tag">{lab.label}</a>
						{/each}
					</td>{/if}
					{#if showCorrespondingColumn && col('corr')}<td class="corr-cell">
						{#if p.is_corresponding}<span title="Auteur correspondant">&#10003;</span>{/if}
					</td>{/if}
					{#if col('apc')}<td class="apc-cell">
						{#if p.apc}
							{@const ucaApc = p.apc.filter(a => a.in_perimeter)}
							{@const isPersonNonCorr = apcMode === 'person' &&!p.is_corresponding}
							{#if ucaApc.length > 0}
								<span class="apc-tag" class:apc-other={isPersonNonCorr}
									title={ucaApc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.lab_acronym || institution.name})`).join('\n') + (isPersonNonCorr ? '\nAuteur non correspondant' : '')}>
									{Math.round(ucaApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{:else}
								<span class="apc-tag apc-other" title={p.apc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.institution || '?'})`).join('\n')}>
									{Math.round(p.apc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{/if}
						{/if}
					</td>{/if}
					{#if col('oa_status')}<td>
						{#if p.oa_status && p.oa_status !== 'unknown'}
							<span class="oa-tag oa-{p.oa_status}">{oaStatusLabel(p.oa_status)}</span>
						{/if}
					</td>{/if}
					{#if col('license')}<td class="license-cell">{p.license ? (licenseNames[p.license] ?? p.license) : ''}</td>{/if}
					{#if showHalStatusColumn && col('hal_status')}
						{@const hs = computeHalStatus(p)}
						{@const meta = HAL_STATUS_META[hs]}
						<td><span class="hal-badge {meta.css}">{meta.label}</span></td>
					{/if}
					{#if col('sources')}<td class="links-cell">
						{#if p.hal_id}
							<a href={p.record_urls.hal} target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
								<img src={asset('icons/hal.ico')} alt="HAL" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.openalex_id}
							<a href={p.record_urls.openalex} target="_blank" rel="noopener" class="source-tag source-openalex" title="OpenAlex: {p.openalex_id}">
								<img src={asset('icons/openalex.png')} alt="OA" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.scanr_id}
							<a href={p.record_urls.scanr} target="_blank" rel="noopener" class="source-tag source-scanr" title="ScanR: {p.scanr_id}">
								<img src={asset('scanr-icon.svg')} alt="ScanR" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.wos_id}
							<a href={p.record_urls.wos} target="_blank" rel="noopener" class="source-tag source-wos" title="WoS: {p.wos_id}">
								<img src={asset('icons/wos.ico')} alt="WoS" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
					</td>{/if}
					<td class="access-cell"><AccessButton accessUrl={p.access_url} oaStatus={p.oa_status} compact /></td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>
</div>

<Pagination page={listing.page} pages={listing.pages} onchange={(p) => { listing.goToPage(p); syncUrl(); }} />

<style>
	.license-cell {
		font-size: 0.8rem;
	}
	/* Deux lignes : commandes (recherche extensible, compte, exports, lien stats) puis facettes. */
	.publication-toolbar { display: flex; flex-direction: column; gap: 8px; }
	.publication-toolbar .toolbar { margin-bottom: 0; }
	.publication-search { flex: 1; min-width: 220px; }
	.facets-label { font-size: 0.9rem; color: var(--muted); white-space: nowrap; }
	.more-filters-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		height: 34px;
		padding: 0 10px;
		border: none;
		border-radius: var(--radius);
		background: none;
		font: inherit;
		font-size: 0.9rem;
		color: var(--text-secondary);
		white-space: nowrap;
		cursor: pointer;
	}
	.more-filters-btn:hover,
	.more-filters-btn.open { background: var(--hover); }
	/* Facettes optionnelles sur une ligne, rubriques séparées par un filet vertical. */
	.more-filters {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 0;
	}
	.filter-group { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
	.filter-group + .filter-group {
		margin-left: 10px;
		padding-left: 10px;
		border-left: 1px solid var(--border);
	}
	.publication-table { min-width: 760px; }
	.publication-table tr.active-row td { background: var(--accent-light); }
	.col-menu-th { position: relative; }
	.access-cell { white-space: nowrap; }

	/* Statut HAL (lab) */
	.hal-badge {
		display: inline-block;
		padding: 2px 7px;
		border-radius: var(--radius);
		font-size: 0.8rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.hal-ok              { background: var(--success-light); color: var(--success); }
	.hal-notice          { background: #fff3e0; color: #c77c00; }
	.hal-hors-collection { background: #ffe8d6; color: #d35400; }
	.hal-hors-hal        { background: var(--danger-light); color: var(--danger); }

	/* Auteur correspondant (person) */
	.corr-cell { text-align: center; color: var(--accent); font-size: 0.85rem; }

	/* Bouton exclure (admin, person) */
	.exclude-cell { padding: 0 2px !important; text-align: center; vertical-align: middle; }
	.exclude-btn {
		background: none; border: none; cursor: pointer;
		color: var(--text-faint); font-size: 0.85rem; padding: 2px 4px;
		border-radius: var(--radius); line-height: 1; transition: color 0.15s, background 0.15s;
	}
	.exclude-btn:hover { color: var(--danger); background: var(--danger-light); }
</style>
