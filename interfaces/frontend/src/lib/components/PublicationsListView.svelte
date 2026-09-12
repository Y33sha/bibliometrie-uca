<script lang="ts">
	import { institution } from '$lib/institution.svelte';
	import { onMount } from 'svelte';
	import { autofocus } from '$lib/actions/focus';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { halDocUrl, scanrPubUrl } from '$lib/utils';
	import PublicationTitle from '$lib/components/PublicationTitle.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import EntityFilter from '$lib/components/EntityFilter.svelte';
	import PresenceFilterToggle from '$lib/components/PresenceFilterToggle.svelte';
	import ActiveFilterBar from '$lib/components/ActiveFilterBar.svelte';
	import { SOURCE_ITEMS } from '$lib/filterItems';
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
	} from '$lib/filterRegistry';
	import Pagination from '$lib/components/Pagination.svelte';
	import { oaLabelsMap } from '$lib/labels';
	import {
		docTypeSingular,
		docTypePlural,
		docTypeFamilies,
		publicationsDocTypes,
		docTypeFilterToken,
		docTypeFilterFromToken,
	} from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import { useColumnVisibility } from '$lib/composables/useColumnVisibility.svelte';
	import ColumnMenu from '$lib/components/ColumnMenu.svelte';
	import { paramsToQuery } from '$lib/utils';

	import type { components } from '$lib/api/schema';
	type Publication = components['schemas']['PublicationListItem'] & {
		// Champs présents quand l'API est appelée avec `person_id` (cf. routes /api/publications côté backend qui enrichit la réponse). Optionnels car non garantis hors contexte personne.
		is_corresponding?: boolean | null;
		authorship_id?: number | null;
		hal_collections?: string[] | null;
	};

	// --- Props ---
	// Composant de liste de publications réutilisable. Utilisé par :
	// - `/publications` (mode autonome avec sync URL)
	// - `/subjects/[id]?tab=publications` (filtre `subject_id` fixe)
	// - `/laboratories/[id]?tab=publications` (filtre `lab_id` fixe + colonne Statut HAL)
	// - `/persons/[id]?tab=publications` (filtre `person_id` + facets Corresp./Périmètre)
	// - `/journals/[id]?tab=publications` (filtre `journal_id` fixe)
	// - `/publishers/[id]?tab=publications` (filtre `publisher_id` fixe)
	interface ExternalFilters {
		subjectId?: number;
		subjectLabel?: string;
		labId?: number;
		labLabel?: string;
		/** Collection HAL du laboratoire (ex 'lmbp'). Requis pour calculer la colonne « Statut HAL ». */
		halCollection?: string;
		personId?: number;
		personLabel?: string;
		journalId?: number;
		publisherId?: number;
	}
	type ApcMode = 'uca' | 'lab' | 'person-uca';
	let {
		apiKey = 'pub-list',
		externalFilters,
		urlSync = true,
		basePath = '/publications',
		showFilterBanner = true,
		showHalStatusColumn = false,
		showCorrespondingColumn = false,
		showPerimeterFacet = false,
		showAdminExclude = false,
		apcMode = 'uca' as ApcMode,
		perPage = 100,
		restrictToPublications = false,
		onExcludeAuthorship,
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
		/** Affiche la 1ère colonne avec un bouton ✕ pour exclure l'authorship. Le parent gère l'auth check et passe le callback. Si le callback retourne `true` (ou void), la ligne est retirée du tableau ; retourne `false` pour annuler (ex. l'utilisatrice a cliqué Annuler dans un confirm). */
		showAdminExclude?: boolean;
		/** Mode de rendu du tag APC :
		 *  - 'uca' : paiements sur un budget du périmètre de l'établissement (défaut)
		 *  - 'lab' : filtre par lab_id === externalFilters.labId
		 *  - 'person-uca' : 'uca' + classe `apc-other` si !is_corresponding */
		apcMode?: ApcMode;
		/** Nombre d'éléments par page (50 pour les onglets, 100 pour /publications). */
		perPage?: number;
		/** Par défaut, restreint la liste à la famille « Publications » (au sens strict) tant qu'aucun type n'est coché. Réservé à la liste générale ; les listes embarquées (journal, éditeur, personne…) restent permissives. L'utilisatrice élargit via la facet « Types ». */
		restrictToPublications?: boolean;
		onExcludeAuthorship?: (authorshipId: number, pubId: number) => void | boolean | Promise<void | boolean>;
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
		{ key: 'title',      label: 'Titre',      fixed: true },
		{ key: 'journal',    label: 'Revue' },
		{ key: 'publisher',  label: 'Éditeur' },
		// svelte-ignore state_referenced_locally
		...(hasFixedLab ? [] : [{ key: 'labs', label: 'Labo(s)' }]),
		// svelte-ignore state_referenced_locally
		...(showCorrespondingColumn ? [{ key: 'corr', label: 'Corresp.' }] : []),
		{ key: 'apc',        label: 'APC' },
		{ key: 'oa',         label: 'OA' },
		{ key: 'oa_status',    label: 'Voie OA' },
		// svelte-ignore state_referenced_locally
		...(showHalStatusColumn ? [{ key: 'hal_status', label: 'Statut HAL' }] : []),
		{ key: 'links',      label: 'Liens',      fixed: true },
	];
	const initialHidden = ['apc', 'oa_status', 'publisher'];
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
			showColumns: ['oa', 'oa_status'],
		},
		{
			key: 'journal',
			control: 'entity',
			label: 'Revue',
			param: 'journal_id',
			entity: 'journal',
			group: 'Revue et éditeur',
			fixed: () => fixedId(externalFilters?.journalId),
			showColumns: ['journal'],
		},
		{
			key: 'publisher',
			control: 'entity',
			label: 'Éditeur',
			param: 'publisher_id',
			entity: 'publisher',
			group: 'Revue et éditeur',
			fixed: () => fixedId(externalFilters?.publisherId),
			showColumns: ['journal'],
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
			group: 'Accès ouvert',
			showColumns: ['oa', 'oa_status'],
		},
		{
			key: 'halStatus',
			control: 'checkbox',
			label: 'Statut HAL',
			param: 'hal_status',
			facet: { type: 'labeled', apiKey: 'hal_status' },
			group: 'Accès ouvert',
			enabled: () => showHalStatusColumn,
			showColumns: ['hal_status'],
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
			facet: { type: 'boolean', apiKey: 'corresponding', yesLabel: 'Oui', noLabel: 'Non' },
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
			key: 'sources',
			control: 'presence',
			label: 'Sources',
			param: 'source_filter',
			group: 'Sources',
			items: SOURCE_ITEMS,
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
	const showStatsLink = $derived(!externalFilters?.personId && !externalFilters?.subjectId);
	const statsUrl = $derived.by(() => {
		const p = new URLSearchParams();
		const { checkbox, entity } = values;
		if (checkbox.years.length) p.set('year', checkbox.years.join(','));
		p.set('doc_type', docTypeFilterToken(checkbox.docTypes));
		if (checkbox.oa.length) p.set('oa_status', checkbox.oa.join(','));
		if (checkbox.apc.length) p.set('has_apc', checkbox.apc.join(','));
		// Laboratoire : fixé par la route ou choisi en facette (« aucun labo » n'a pas de sens côté stats).
		const labId =
			externalFilters?.labId != null
				? String(externalFilters.labId)
				: checkbox.labs.filter((v) => v !== 'none').join(',');
		if (labId) p.set('lab_id', labId);
		// Éditeur / revue : fixés par la route ou choisis en facette.
		const publisherId = fixedId(externalFilters?.publisherId) ?? entity.publisher;
		if (publisherId) p.set('publisher_id', publisherId);
		const journalId = fixedId(externalFilters?.journalId) ?? entity.journal;
		if (journalId) p.set('journal_id', journalId);
		return base + '/stats?' + paramsToQuery(p);
	});

	// Sort display
	const yearSortArrow = $derived(currentSort === 'year_asc' ? '▲' : currentSort === 'year_desc' ? '▼' : '');
	const titleSortArrow = $derived(currentSort === 'title_asc' ? '▲' : currentSort === 'title_desc' ? '▼' : '');
	const apcSortArrow = $derived(currentSort === 'apc_asc' ? '▲' : currentSort === 'apc_desc' ? '▼' : '');
	const yearSortActive = $derived(currentSort === 'year_desc' || currentSort === 'year_asc');
	const titleSortActive = $derived(currentSort === 'title_asc' || currentSort === 'title_desc');
	const apcSortActive = $derived(currentSort === 'apc_desc' || currentSort === 'apc_asc');

	// --- Shared filter params builder ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('excluded_doc_type', 'ongoing_thesis');
		if (externalFilters?.personId != null) params.set('person_id', String(externalFilters.personId));
		if (externalFilters?.subjectId) params.set('subject_id', String(externalFilters.subjectId));
		appendFilterParams(FILTERS, values, params);
		return params;
	}

	// --- Composables ---
	const pubs = usePaginatedFetch<Publication>({
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
			currentPage: pubs.page,
		}));
	}

	function onFilterChange() {
		pubs.page = 1;
		syncUrl();
		pubs.load();
		facets.load();
	}

	function onCheckboxChange(filter: CheckboxFilter, selected: string[]) {
		values.checkbox[filter.key] = filter.normalize ? filter.normalize(selected) : selected;
		onFilterChange();
	}

	function onEntityChange(filter: EntityChoiceFilter, id: string | null) {
		values.entity[filter.key] = id;
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
		pubs.page = 1;
		syncUrl();
		pubs.load();
		facets.load();
	});

	function toggleSortYear() {
		currentSort = currentSort === 'year_desc' ? 'year_asc' : 'year_desc';
		onFilterChange();
	}

	function toggleSortTitle() {
		currentSort = currentSort === 'title_asc' ? 'title_desc' : 'title_asc';
		onFilterChange();
	}

	function toggleSortApc() {
		currentSort = currentSort === 'apc_desc' ? 'apc_asc' : 'apc_desc';
		onFilterChange();
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		const q = search.trim();
		if (q) params.set('search', q);
		// Colonnes visibles → le CSV reflète le tableau affiché.
		params.set('columns', cv.visibleColumns.join(','));
		return `${base}/api/publications/export.csv?${paramsToQuery(params)}`;
	}

	async function onExcludeClick(p: Publication) {
		if (!onExcludeAuthorship || p.authorship_id == null) return;
		const result = await onExcludeAuthorship(p.authorship_id, p.id);
		// `false` = annulé par le parent (ex. l'utilisatrice a cliqué Annuler) ; `true` ou `undefined` = succès → on retire la ligne du tableau.
		if (result === false) return;
		pubs.items = pubs.items.filter((item) => item.id !== p.id);
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			restoreValues(FILTERS, restored, values);
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) pubs.page = restored.currentPage as number;
		}

		// Défaut « Publications » (liste générale uniquement) : sans filtre de type explicite dans l'URL, on pré-sélectionne la famille Publications. La sélection est réelle (et non un filtre caché), donc la facet « Types » la reflète ; cocher d'autres types ou « Tous » l'élargit. Le token `all` dans l'URL (« Tous » explicite) laisse la sélection vide.
		if (restrictToPublications && !(urlSync && $page.url.searchParams.has('doc_type'))) {
			values.checkbox.docTypes = [...publicationsDocTypes];
		}

		// Forcer l'affichage des colonnes liées aux filtres actifs
		const needed = activeColumns(FILTERS, values);
		if (needed.length) cv.ensure(needed);

		await facets.load();
		pubs.load();
	});
</script>

{#if showFilterBanner && subjectBannerText}
	<div class="filter-banner">Filtre actif : {subjectBannerText}</div>
{/if}

<div class="toolbar-card toolbar-sticky pub-toolbar">
	<div class="toolbar pub-toolbar-main">
		<input type="search" class="pub-search" placeholder="Rechercher par titre ou sujet..." bind:value={search} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
		<span class="count">{pubs.total} publication{pubs.total > 1 ? 's' : ''}</span>
		<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
		{#if showStatsLink}<a href={statsUrl} class="pub-link">Statistiques &rarr;</a>{/if}
	</div>
	<div class="toolbar pub-toolbar-facets">
		<span class="facets-label">Filtrer par&nbsp;:</span>
		{#each sections.primary as f (f.key)}
			{#if isShown(f, optionCount)}{@render filterControl(f)}{/if}
		{/each}
		<button type="button" class="more-filters-btn" class:open={showMoreFilters} aria-expanded={showMoreFilters} onclick={() => (showMoreFilters = !showMoreFilters)}>
			Plus de filtres
			{#if moreFiltersActive > 0}<span class="more-filters-badge">{moreFiltersActive}</span>{/if}
			<span class="more-filters-arrow">{showMoreFilters ? '▴' : '▾'}</span>
		</button>
	</div>
	{#if showMoreFilters}
		<div class="more-filters">
			{#each sections.groups as g (g.label)}
				{@const shown = g.filters.filter((f) => isShown(f, optionCount))}
				{#if shown.length}
					<div class="filter-group">
						<span class="filter-group-label">{g.label}</span>
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
		<EntityFilter label={f.label} endpoint="/api/publications/facets" kind={f.entity} buildParams={buildFilterParams} selectedId={values.entity[f.key]} onchange={(id) => onEntityChange(f, id)} />
	{:else}
		<PresenceFilterToggle label={f.label} items={f.items} bind:states={values.presence[f.key]} counts={facets.sourceCounts} onchange={onFilterChange} />
	{/if}
{/snippet}

<div class="table-scroll">
<table class="pub-table">
	<thead>
		<tr>
			{#if showAdminExclude}<th style="width:28px"></th>{/if}
			{#if col('type')}<th style="width:80px">Type</th>{/if}
			{#if col('year')}<th style="width:40px" class="sortable" class:active={yearSortActive} onclick={toggleSortYear}>
				An. <span class="sort-arrow">{yearSortArrow}</span>
			</th>{/if}
			<th class="sortable pub-col-title" class:active={titleSortActive} onclick={toggleSortTitle}>
				Titre <span class="sort-arrow">{titleSortArrow}</span>
			</th>
			{#if col('journal')}<th class="pub-col-journal">Revue</th>{/if}
			{#if col('publisher')}<th class="pub-col-journal">Éditeur</th>{/if}
			{#if !hasFixedLab && col('labs')}<th style="width:80px">Labo(s)</th>{/if}
			{#if showCorrespondingColumn && col('corr')}<th style="width:30px" title="Auteur correspondant">&#9993;</th>{/if}
			{#if col('apc')}<th style="width:60px" class="sortable" class:active={apcSortActive} onclick={toggleSortApc}>
				APC <span class="sort-arrow">{apcSortArrow}</span>
			</th>{/if}
			{#if col('oa')}<th style="width:75px" title="Open Access">OA</th>{/if}
			{#if col('oa_status')}<th style="width:60px">Voie OA</th>{/if}
			{#if showHalStatusColumn && col('hal_status')}<th style="width:100px">Statut HAL</th>{/if}
			<th style="width:80px" class="col-menu-th">
				<ColumnMenu columns={cv.columns} visibleColumns={cv.visibleColumns}
					showMenu={cv.showMenu}
					onToggle={cv.toggle}
					onClose={() => cv.showMenu = false}
					onOpen={() => cv.showMenu = !cv.showMenu} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#if pubs.items.length === 0}
			<TableStatusRow loading={pubs.loading} colspan={cv.visibleColumns.length + (showAdminExclude ? 1 : 0)} emptyText="Aucune publication trouvée" />
		{:else}
			{#each pubs.items as p (p.id)}
				<tr>
					{#if showAdminExclude}
						<td class="exclude-cell">
							{#if p.authorship_id != null}
								<button class="exclude-btn" title="Exclure ce lien auteur–publication"
									onclick={() => onExcludeClick(p)}>✕</button>
							{/if}
						</td>
					{/if}
					{#if col('type')}<td>
						<span class="type-label">{docTypeSingular[p.doc_type || ''] || p.doc_type || ''}</span>
					</td>{/if}
					{#if col('year')}<td>{p.pub_year || ''}</td>{/if}
					<td><a href="{base}/publications/{p.id}" class="pub-title"><PublicationTitle titre={p.title} /></a></td>
					{#if col('journal')}<td class="journal-cell pub-col-journal">
						{#if p.journal_id}
							<a href="{base}/journals/{p.journal_id}">{p.journal}</a>
						{:else}
							{p.journal || ''}
						{/if}
					</td>{/if}
					{#if col('publisher')}<td class="journal-cell pub-col-journal">
						{#if p.publisher_id}
							<a href="{base}/publishers/{p.publisher_id}">{p.publisher}</a>
						{:else}
							{p.publisher || ''}
						{/if}
					</td>{/if}
					{#if !hasFixedLab && col('labs')}<td>
						{#each p.lab_items || [] as lab}
							<a href="{base}/laboratories/{lab.id}" class="lab-tag">{lab.label}</a>
						{/each}
					</td>{/if}
					{#if showCorrespondingColumn && col('corr')}<td class="corr-cell">
						{#if p.is_corresponding}<span title="Auteur correspondant">&#10003;</span>{/if}
					</td>{/if}
					{#if col('apc')}<td class="apc-cell">
						{#if p.apc}
							{#if apcMode === 'lab'}
								{@const thisLabApc = p.apc.filter(a => a.lab_id === externalFilters?.labId)}
								{@const otherApc = p.apc.filter(a => a.lab_id !== externalFilters?.labId)}
								{#if thisLabApc.length > 0}
									<span class="apc-tag" title={thisLabApc.map(a => `${a.amount?.toLocaleString('fr-FR')} €`).join('\n')}>
										{Math.round(thisLabApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
									</span>
								{:else if otherApc.length > 0}
									<span class="apc-tag apc-other" title={otherApc.map(a => `sur budget ${a.lab_acronym || a.institution || '?'}`).join('\n')}>
										{Math.round(otherApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
									</span>
								{/if}
							{:else}
								{@const ucaApc = p.apc.filter(a => a.in_perimeter)}
								{@const isPersonNonCorr = apcMode === 'person-uca' && !p.is_corresponding}
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
						{/if}
					</td>{/if}
					{#if col('oa')}<td class="oa-lock-cell">
						{#if p.oa_status === 'embargoed'}
							<span class="oa-lock-badge oa-lock-embargo">
								<img src="{base}/hourglass.svg" alt="Sous embargo" class="oa-lock" title="Sous embargo : dépôt existant, accès différé" />
								<span class="oa-lock-label">embargo</span>
							</span>
						{:else if p.oa_status && !['unknown', 'closed'].includes(p.oa_status)}
							<span class="oa-lock-badge oa-lock-open">
								<img src="{base}/lock-open.svg" alt="Open Access" class="oa-lock" title="Open Access ({p.oa_status})" />
								<span class="oa-lock-label">ouvert</span>
							</span>
						{:else}
							<span class="oa-lock-badge oa-lock-closed">
								<img src="{base}/lock-closed.svg" alt="Closed" class="oa-lock" title="Accès fermé" />
								<span class="oa-lock-label">fermé</span>
							</span>
						{/if}
					</td>{/if}
					{#if col('oa_status')}<td>
						{#if p.oa_status && p.oa_status !== 'unknown'}
							<span class="oa-tag oa-{p.oa_status}">{p.oa_status}</span>
						{/if}
					</td>{/if}
					{#if showHalStatusColumn && col('hal_status')}
						{@const hs = computeHalStatus(p)}
						{@const meta = HAL_STATUS_META[hs]}
						<td><span class="hal-badge {meta.css}">{meta.label}</span></td>
					{/if}
					<td class="links-cell">
						{#if p.hal_id}
							<a href={halDocUrl(p.hal_id, p.oa_status)} target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
								<img src="{base}/icons/hal.ico" alt="HAL" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.openalex_id}
							<a href="https://openalex.org/{p.openalex_id}" target="_blank" rel="noopener" class="source-tag source-openalex" title="OpenAlex: {p.openalex_id}">
								<img src="{base}/icons/openalex.png" alt="OA" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.scanr_id}
							<a href={scanrPubUrl(p.scanr_id)} target="_blank" rel="noopener" class="source-tag source-scanr" title="ScanR: {p.scanr_id}">
								<img src="{base}/scanr-icon.svg" alt="ScanR" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.wos_id}
							<a href="https://www.webofscience.com/wos/woscc/full-record/{p.wos_id}" target="_blank" rel="noopener" class="source-tag source-wos" title="WoS: {p.wos_id}">
								<img src="{base}/icons/wos.ico" alt="WoS" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.doi}
							<a href="https://doi.org/{p.doi}" target="_blank" rel="noopener" class="source-tag source-doi" title={p.doi}>
								<svg viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
									<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
									<polyline points="15 3 21 3 21 9"/>
									<line x1="10" y1="14" x2="21" y2="3"/>
								</svg>
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
					</td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>
</div>

<Pagination page={pubs.page} pages={pubs.pages} onchange={(p) => { pubs.goToPage(p); syncUrl(); }} />

<style>
	.filter-banner {
		background: var(--accent-light);
		border: 1px solid #c4d8ed;
		border-radius: 5px;
		padding: 8px 14px;
		margin-bottom: 12px;
		font-size: 0.95rem;
		color: #2c3e50;
	}
	/* Deux lignes : commandes (recherche extensible, compte, exports, lien stats) puis facettes. */
	.pub-toolbar { display: flex; flex-direction: column; gap: 8px; }
	.pub-toolbar .toolbar { margin-bottom: 0; }
	.pub-search { flex: 1; min-width: 220px; }
	.pub-link {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 6px 12px;
		background: var(--accent);
		color: white;
		text-decoration: none;
		border-radius: 5px;
		font-size: 0.9rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.pub-link:hover { opacity: 0.9; }
	.facets-label { font-size: 0.9rem; color: var(--muted); white-space: nowrap; }
	.more-filters-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 6px 10px;
		border: 1px dashed var(--border);
		border-radius: 4px;
		background: none;
		font: inherit;
		font-size: 0.95rem;
		color: var(--accent);
		white-space: nowrap;
		cursor: pointer;
	}
	.more-filters-btn:hover,
	.more-filters-btn.open { border-color: var(--accent); }
	.more-filters-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		background: var(--accent);
		color: white;
		font-size: 0.8rem;
		font-weight: 600;
	}
	.more-filters-arrow { font-size: 0.7rem; }
	/* Panneau « Plus de filtres » : une ligne par rubrique, libellé à gauche. */
	.more-filters {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding-top: 8px;
		border-top: 1px solid var(--border-subtle);
	}
	.filter-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.filter-group-label {
		width: 130px;
		flex-shrink: 0;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
	}
	.pub-table {
		width: 100%;
		min-width: 760px;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		/* pas d'overflow: hidden → le dropdown ColumnMenu peut déborder sous la dernière ligne sans être clippé (coins arrondis restent visuellement corrects grâce à border-collapse). */
	}
	.pub-table th {
		background: var(--surface);
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.pub-table td {
		padding: 7px 10px;
		border-bottom: 1px solid var(--border-subtle);
		font-size: 0.95rem;
		vertical-align: top;
	}
	.pub-table tr:hover td { background: var(--surface-hover); }
	.col-menu-th { position: relative; }

	/* Statut HAL (lab) */
	.hal-badge {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
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
		color: #ccc; font-size: 0.85rem; padding: 2px 4px;
		border-radius: 3px; line-height: 1; transition: color 0.15s, background 0.15s;
	}
	.exclude-btn:hover { color: var(--danger); background: #fdeaea; }
</style>
