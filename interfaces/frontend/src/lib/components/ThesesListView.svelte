<script lang="ts">
	import { onMount } from 'svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { page } from '$app/state';
	import { withBase } from '#lib/paths.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import ThesesTable, { useThesisColumns } from '#lib/components/ThesesTable.svelte';
	import type { PublicationSort, ThesisRow, ThesisSortColumn } from '#lib/components/ThesesTable.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { nextSort } from '#lib/sort.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { PUBLICATION_FACETS_ENDPOINT, usePublicationFacets } from '#lib/composables/usePublicationFacets.svelte.js';
	import { useFilterPanel } from '#lib/composables/useFilterPanel.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { activeCount, appendFilterParams, initialValues, restoreValues, urlFilterDefs, urlState } from '#lib/filterRegistry.js';
	import { THESIS_DOC_TYPES, THESIS_FILTER_GROUPS, thesisFilters } from '#lib/thesisFilters.js';
	import { paramsToQuery } from '#lib/utils.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import PublicationDrawer from '#lib/components/publications/PublicationDrawer.svelte';

	// Vue-liste des thèses réutilisable. Utilisée par :
	// - `/theses` (mode autonome avec sync URL)
	// - `/structures/[id]?tab=theses` (labo fixe via `labId`, sans sync URL)
	let {
		apiKey = 'theses-list',
		labId,
		urlSync = true,
		basePath = '/theses',
		perPage = 100
	}: {
		apiKey?: string;
		/** Contexte labo fixe : borne les résultats à ce labo et masque la facette Laboratoire. */
		labId?: number;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
	} = $props();

	// svelte-ignore state_referenced_locally
	const columns = useThesisColumns(labId == null);

	// Volet d'une thèse : ouvert tant que `?publication=<id>` figure dans l'URL.
	const drawer = useDrawerParam('publication');

	// svelte-ignore state_referenced_locally
	const FILTERS = thesisFilters(labId);
	let values = $state(initialValues(FILTERS));
	const filterPanel = useFilterPanel();
	let search = $state('');
	let currentSort: PublicationSort = $state('soutenance_desc');

	// Filtres et terme de recherche. Sans filtre de statut, les thèses soutenues et en cours.
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams({ doc_type: THESIS_DOC_TYPES });
		appendFilterParams(FILTERS, values, params);
		const q = search.trim();
		if (q) params.set('search', q);
		return params;
	}

	const listing = usePaginatedFetch<ThesisRow>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			return params;
		}
	});

	const facets = usePublicationFacets({
		filters: FILTERS,
		apiKey: () => `${apiKey}-facets`,
		buildParams: buildFilterParams
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			...urlFilterDefs(FILTERS),
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'soutenance_desc' },
			currentPage: { type: 'page', urlKey: 'page' }
		}
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			...urlState(FILTERS, values),
			search,
			currentSort,
			currentPage: listing.page
		}));
	}

	function onFilterChange() {
		listing.page = 1;
		syncUrl();
		listing.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(onFilterChange);

	function toggleSort(column: ThesisSortColumn) {
		const dates: ThesisSortColumn[] = ['inscription', 'soutenance'];
		currentSort = nextSort(currentSort, column, dates.includes(column) ? 'desc' : 'asc');
		onFilterChange();
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		// Colonnes visibles → le CSV reflète le tableau affiché.
		params.set('columns', columns.visibleColumns.join(','));
		return withBase(`/api/publications/export-theses.csv?${paramsToQuery(params)}`);
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			restoreValues(FILTERS, restored, values);
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as PublicationSort;
			if (restored.currentPage) listing.page = restored.currentPage as number;
		}
		await facets.load();
		listing.load();
	});
</script>

<ListToolbar bind:search placeholder="Rechercher par titre ou sujet" onsearch={onSearchInput} list={listing} one="thèse" many="thèses" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={filterPanel.open} active={activeCount(FILTERS, values)} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values options={facets.options} onchange={onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={filterPanel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={THESIS_FILTER_GROUPS} bind:values options={facets.options} presenceCounts={facets.sourceCounts} loaded={facets.loaded} entityEndpoint={PUBLICATION_FACETS_ENDPOINT} buildParams={buildFilterParams} panel={filterPanel} onchange={onFilterChange} />
	{/snippet}
	<ThesesTable items={listing.items} loading={listing.loading} error={listing.error} sort={currentSort} onToggleSort={toggleSort} {columns} onopen={drawer.open} activeId={drawer.id} />
	<Pagination
		page={listing.page}
		pages={listing.pages}
		onchange={(p: number) => {
			listing.page = p;
			syncUrl();
			listing.load();
		}}
	/>
</FilterLayout>

{#if drawer.id !== null}
	<PublicationDrawer
		publicationId={drawer.id}
		onclose={() => drawer.open(null)}
		onopen={drawer.open}
		onchange={() => {
			listing.load();
			facets.load();
		}}
	/>
{/if}
