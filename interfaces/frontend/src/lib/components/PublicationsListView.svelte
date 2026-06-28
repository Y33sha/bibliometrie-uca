<script lang="ts">
	import { onMount } from 'svelte';
	import { autofocus } from '$lib/actions/focus';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { sanitizeTitle, halDocUrl, scanrPubUrl } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import EntityFilter from '$lib/components/EntityFilter.svelte';
	import PresenceFilterToggle from '$lib/components/PresenceFilterToggle.svelte';
	import { SOURCE_ITEMS } from '$lib/filterItems';
	import Pagination from '$lib/components/Pagination.svelte';
	import { oaLabelsMap } from '$lib/labels';
	import { docTypeSingular, docTypePlural, docTypeFamilies } from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import { useColumnVisibility } from '$lib/composables/useColumnVisibility.svelte';
	import ColumnMenu from '$lib/components/ColumnMenu.svelte';

	import type { components } from '$lib/api/schema';
	type Publication = components['schemas']['PublicationListItem'] & {
		// Champs présents quand l'API est appelée avec `person_id` (cf. routes
		// /api/publications côté backend qui enrichit la réponse). Optionnels
		// car non garantis hors contexte personne.
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
		/** Collection HAL du laboratoire (ex 'lmbp'). Requis pour calculer
		 *  la colonne « Statut HAL ». */
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
		/** Affiche la colonne et la facet « Statut HAL ». Requiert
		 *  `externalFilters.halCollection` pour le calcul du badge. */
		showHalStatusColumn?: boolean;
		/** Affiche la colonne et la facet « Auteur correspondant ». */
		showCorrespondingColumn?: boolean;
		/** Affiche la facet « UCA » (in_perimeter). */
		showPerimeterFacet?: boolean;
		/** Affiche la 1ère colonne avec un bouton ✕ pour exclure l'authorship.
		 *  Le parent gère l'auth check et passe le callback. Si le callback
		 *  retourne `true` (ou void), la ligne est retirée du tableau ;
		 *  retourne `false` pour annuler (ex. user a cliqué Annuler dans un
		 *  confirm). */
		showAdminExclude?: boolean;
		/** Mode de rendu du tag APC :
		 *  - 'uca' : filtre par budget_structure_id === 169 (défaut)
		 *  - 'lab' : filtre par lab_id === externalFilters.labId
		 *  - 'person-uca' : 'uca' + classe `apc-other` si !is_corresponding */
		apcMode?: ApcMode;
		/** Nombre d'éléments par page (50 pour les onglets, 100 pour /publications). */
		perPage?: number;
		/** Par défaut, restreint la liste à la famille « Publications » (au sens strict) tant
		 *  qu'aucun type n'est coché. Réservé à la liste générale ; les listes embarquées (journal,
		 *  éditeur, personne…) restent permissives. L'utilisatrice élargit via la facet « Types ». */
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
	// Ordre des colonnes = ordre dans le tableau. Les colonnes optionnelles
	// (hal_status, corr) ne sont incluses dans la liste que si la prop
	// correspondante est activée — sinon l'utilisatrice n'a pas à les voir
	// dans le menu de visibilité.
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

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('year_desc');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let sourceStates = $state<Record<string, 'all' | 'yes' | 'no'>>({});
	let selectedDocTypes: string[] = $state([]);
	let selectedAccess: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let selectedCountries: string[] = $state([]);
	let selectedHalStatus: string[] = $state([]);
	let selectedCorr: string[] = $state([]);
	let selectedPerimeter: string[] = $state([]);

	// External filters (from stats page)
	let filterPublisherId: string | null = $state(null);
	let filterJournalId: string | null = $state(null);
	let filterPublisherName: string | null = $state(null);
	let filterJournalName: string | null = $state(null);

	// Éditeur et revue sont des facettes (recherche serveur) ; leur sélection libre vit dans
	// `filterPublisherId`/`filterJournalId` (+ libellés). Le bandeau ne signale plus que le sujet,
	// contexte fixé par la route (sans facette propre ici).
	const subjectBannerText = $derived(
		externalFilters?.subjectId
			? 'sujet = ' + (externalFilters.subjectLabel ?? `#${externalFilters.subjectId}`)
			: '',
	);

	// Sélection courante des facettes éditeur / revue (id + libellé restaurés de l'URL).
	const publisherSelection = $derived(
		filterPublisherId ? { value: filterPublisherId, text: filterPublisherName ?? filterPublisherId } : null,
	);
	const journalSelection = $derived(
		filterJournalId ? { value: filterJournalId, text: filterJournalName ?? filterJournalId } : null,
	);

	function onPublisherFilter(e: { value: string; text: string } | null) {
		filterPublisherId = e?.value ?? null;
		filterPublisherName = e?.text ?? null;
		onFilterChange();
	}
	function onJournalFilter(e: { value: string; text: string } | null) {
		filterJournalId = e?.value ?? null;
		filterJournalName = e?.text ?? null;
		onFilterChange();
	}

	// Sort display
	const yearSortArrow = $derived(currentSort === 'year_asc' ? '▲' : currentSort === 'year_desc' ? '▼' : '');
	const titleSortArrow = $derived(currentSort === 'title' ? '▲' : currentSort === 'title_desc' ? '▼' : '');
	const apcSortArrow = $derived(currentSort === 'apc_asc' ? '▲' : currentSort === 'apc_desc' ? '▼' : '');
	const yearSortActive = $derived(currentSort === 'year_desc' || currentSort === 'year_asc');
	const titleSortActive = $derived(currentSort === 'title' || currentSort === 'title_desc');
	const apcSortActive = $derived(currentSort === 'apc_desc' || currentSort === 'apc_asc');

	// --- Shared filter params builder ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('excluded_doc_type', 'ongoing_thesis');
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		// `lab_id` : soit imposé par la route (externalFilters.labId), soit
		// choisi par l'utilisatrice via la facet "Laboratoires". Les deux
		// modes sont exclusifs (la facet est masquée si labId est fixe).
		if (externalFilters?.labId != null) {
			params.set('lab_id', String(externalFilters.labId));
		} else if (selectedLabs.length) {
			params.set('lab_id', selectedLabs.join(','));
		}
		if (externalFilters?.personId != null) params.set('person_id', String(externalFilters.personId));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedAccess.length) params.set('access', selectedAccess.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) params.set('has_apc', selectedApc.join(','));
		if (selectedCountries.length) params.set('country', selectedCountries.join(','));
		if (selectedHalStatus.length) params.set('hal_status', selectedHalStatus.join(','));
		if (selectedCorr.length) params.set('is_corresponding', selectedCorr.join(','));
		if (selectedPerimeter.length) params.set('in_perimeter', selectedPerimeter.join(','));
		// `publisher_id` : externalFilters (/publishers/[id]) ou URL.
		if (externalFilters?.publisherId != null) {
			params.set('publisher_id', String(externalFilters.publisherId));
		} else if (filterPublisherId) {
			params.set('publisher_id', filterPublisherId);
		}
		// `journal_id` : soit imposé par la route (/journals/[id]), soit choisi
		// par l'utilisatrice via l'URL (?journal_id=). Les deux modes sont
		// exclusifs ; externalFilters l'emporte sur le filtre URL.
		if (externalFilters?.journalId != null) {
			params.set('journal_id', String(externalFilters.journalId));
		} else if (filterJournalId) {
			params.set('journal_id', filterJournalId);
		}
		if (externalFilters?.subjectId) params.set('subject_id', String(externalFilters.subjectId));
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
		// Inclut le terme de recherche pour que les comptes de facettes suivent le
		// champ de recherche (comme la liste), pas seulement les autres filtres.
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
		sourceCountsKey: 'source_counts',
		facets: {
			years:         { type: 'simple',      apiKey: 'years' },
			labs:          { type: 'labeled',     apiKey: 'labs' },
			docTypes:      { type: 'label_map',   apiKey: 'doc_types',   labels: docTypePlural },
			access:        { type: 'passthrough', apiKey: 'access' },
			oa:            { type: 'label_map',   apiKey: 'oa_statuses', labels: oaLabelsMap },
			apc:           { type: 'passthrough', apiKey: 'apc' },
			halStatus:     { type: 'passthrough', apiKey: 'hal_status' },
			corresponding: { type: 'boolean',     apiKey: 'corresponding', yesLabel: 'Oui', noLabel: 'Non' },
			perimeter:     { type: 'passthrough', apiKey: 'in_perimeter' },
			countries:     { type: 'passthrough', apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.text} (${c.value.toUpperCase()})`, count: c.count }) },
		},
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
			selectedYears:     { type: 'string_array',  urlKey: 'year' },
			selectedLabs:      { type: 'string_array',  urlKey: 'lab_id' },
			sourceStates:      { type: 'source_states', urlKey: 'source_filter' },
			selectedDocTypes:  { type: 'string_array',  urlKey: 'doc_type' },
			selectedAccess:    { type: 'string_array',  urlKey: 'access' },
			selectedOa:        { type: 'string_array',  urlKey: 'oa_status' },
			selectedApc:       { type: 'string_array',  urlKey: 'has_apc' },
			selectedCountries: { type: 'string_array',  urlKey: 'country' },
			selectedHalStatus: { type: 'string_array',  urlKey: 'hal_status' },
			selectedCorr:      { type: 'string_array',  urlKey: 'is_corresponding' },
			selectedPerimeter: { type: 'string_array',  urlKey: 'in_perimeter' },
			search:            { type: 'single',        urlKey: 'search' },
			currentSort:       { type: 'single',        urlKey: 'sort', defaultValue: 'year_desc' },
			currentPage:       { type: 'page',          urlKey: 'page' },
			filterPublisherId: { type: 'single',        urlKey: 'publisher_id' },
			filterJournalId:   { type: 'single',        urlKey: 'journal_id' },
			filterPublisherName: { type: 'single',      urlKey: 'publisher_name' },
			filterJournalName:   { type: 'single',      urlKey: 'journal_name' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedYears, selectedLabs, sourceStates, selectedDocTypes,
			selectedAccess, selectedOa, selectedApc, selectedCountries,
			selectedHalStatus, selectedCorr, selectedPerimeter,
			search, currentSort,
			currentPage: pubs.page,
			filterPublisherId, filterJournalId, filterPublisherName, filterJournalName,
		}));
	}

	function onFilterChange() {
		pubs.page = 1;
		syncUrl();
		pubs.load();
		facets.load();
	}

	function onLabChange(newSelection: string[]) {
		const hadNone = selectedLabs.includes('none');
		const hasNone = newSelection.includes('none');
		if (hasNone && !hadNone) selectedLabs = ['none'];
		else if (hasNone && newSelection.length > 1) selectedLabs = newSelection.filter((v) => v !== 'none');
		else selectedLabs = newSelection;
		onFilterChange();
	}

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
		currentSort = currentSort === 'title' ? 'title_desc' : 'title';
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
		return `${base}/api/publications/export.csv?${params}`;
	}

	async function onExcludeClick(p: Publication) {
		if (!onExcludeAuthorship || p.authorship_id == null) return;
		const result = await onExcludeAuthorship(p.authorship_id, p.id);
		// `false` = annulé par le parent (ex. user a cliqué Annuler) ;
		// `true` ou `undefined` = succès → on retire la ligne du tableau.
		if (result === false) return;
		pubs.items = pubs.items.filter((item) => item.id !== p.id);
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
			if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
			if (restored.sourceStates) sourceStates = restored.sourceStates as Record<string, 'all' | 'yes' | 'no'>;
			if (restored.selectedDocTypes) selectedDocTypes = restored.selectedDocTypes as string[];
			if (restored.selectedAccess) selectedAccess = restored.selectedAccess as string[];
			if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
			if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
			if (restored.selectedCountries) selectedCountries = restored.selectedCountries as string[];
			if (restored.selectedHalStatus) selectedHalStatus = restored.selectedHalStatus as string[];
			if (restored.selectedCorr) selectedCorr = restored.selectedCorr as string[];
			if (restored.selectedPerimeter) selectedPerimeter = restored.selectedPerimeter as string[];
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) pubs.page = restored.currentPage as number;
			if (restored.filterPublisherId) filterPublisherId = restored.filterPublisherId as string;
			if (restored.filterJournalId) filterJournalId = restored.filterJournalId as string;
			if (restored.filterPublisherName) filterPublisherName = restored.filterPublisherName as string;
			if (restored.filterJournalName) filterJournalName = restored.filterJournalName as string;
		}

		// Défaut « Publications » (liste générale uniquement) : sans filtre de type explicite dans
		// l'URL, on pré-sélectionne la famille Publications. La sélection est réelle (et non un
		// filtre caché), donc la facet « Types » la reflète ; cocher d'autres types ou « Tous »
		// l'élargit.
		if (restrictToPublications && selectedDocTypes.length === 0) {
			selectedDocTypes = [...(docTypeFamilies.find((f) => f.key === 'publications')?.types ?? [])];
		}

		// Forcer l'affichage des colonnes liées aux filtres actifs
		const needed: string[] = [];
		if (selectedOa.length || selectedAccess.length) needed.push('oa', 'oa_status');
		if (selectedApc.length) needed.push('apc');
		if (filterPublisherId || filterJournalId) needed.push('journal');
		if (selectedDocTypes.length) needed.push('type');
		if (showHalStatusColumn && selectedHalStatus.length) needed.push('hal_status');
		if (showCorrespondingColumn && selectedCorr.length) needed.push('corr');
		if (needed.length) cv.ensure(needed);

		await facets.load();
		pubs.load();
	});
</script>

{#if showFilterBanner && subjectBannerText}
	<div class="filter-banner">Filtre actif : {subjectBannerText}</div>
{/if}

<div class="toolbar toolbar-card toolbar-sticky">
	<input type="search" placeholder="Rechercher par titre..." bind:value={search} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
	{#if col('type')}<FacetDropdown label="Types" options={facets.options.docTypes} groups={docTypeFamilies.map((f) => ({ label: f.label, values: f.types }))} bind:selected={selectedDocTypes} onchange={onFilterChange} />{/if}
	{#if col('year')}<FacetDropdown label="Années" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />{/if}
	{#if !externalFilters?.publisherId}<EntityFilter label="Éditeur" endpoint="/api/publishers" itemsKey="publishers" labelField="name" selected={publisherSelection} onchange={onPublisherFilter} />{/if}
	{#if !externalFilters?.journalId}<EntityFilter label="Revue" endpoint="/api/journals" itemsKey="journals" labelField="title" selected={journalSelection} onchange={onJournalFilter} />{/if}
	{#if !hasFixedLab && col('labs')}<FacetDropdown label="Laboratoires" options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onLabChange} />{/if}
	{#if col('oa')}<FacetDropdown label="Accès" options={facets.options.access} bind:selected={selectedAccess} onchange={onFilterChange} />{/if}
	{#if col('oa_status')}<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />{/if}
	{#if showHalStatusColumn && col('hal_status')}<FacetDropdown label="Statut HAL" options={facets.options.halStatus} bind:selected={selectedHalStatus} onchange={onFilterChange} />{/if}
	{#if showCorrespondingColumn && col('corr') && facets.options.corresponding.length}<FacetDropdown label="Corresp." options={facets.options.corresponding} bind:selected={selectedCorr} onchange={onFilterChange} />{/if}
	{#if showPerimeterFacet && facets.options.perimeter.length}<FacetDropdown label="UCA" options={facets.options.perimeter} bind:selected={selectedPerimeter} onchange={onFilterChange} />{/if}
	{#if col('apc')}<FacetDropdown label="APC" options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />{/if}
	<FacetDropdown label="Pays" options={facets.options.countries} searchable bind:selected={selectedCountries} onchange={onFilterChange} />
	<PresenceFilterToggle label="Sources" items={SOURCE_ITEMS} bind:states={sourceStates} counts={facets.sourceCounts} onchange={onFilterChange} />
	<span class="count">{pubs.total} publication{pubs.total > 1 ? 's' : ''}</span>
	<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
</div>

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
					<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
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
								{@const ucaApc = p.apc.filter(a => a.budget_structure_id === 169)}
								{@const isPersonNonCorr = apcMode === 'person-uca' && !p.is_corresponding}
								{#if ucaApc.length > 0}
									<span class="apc-tag" class:apc-other={isPersonNonCorr}
										title={ucaApc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.lab_acronym || 'UCA'})`).join('\n') + (isPersonNonCorr ? '\nAuteur non correspondant' : '')}>
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
	.toolbar input[type='search'] { width: 280px; }
	.pub-table {
		width: 100%;
		min-width: 760px;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		/* pas d'overflow: hidden → le dropdown ColumnMenu peut déborder
		   sous la dernière ligne sans être clippé (coins arrondis
		   restent visuellement corrects grâce à border-collapse). */
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
