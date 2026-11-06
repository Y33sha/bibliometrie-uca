<script lang="ts">
	import { onMount } from 'svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { withBase } from '#lib/paths.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import ThesesTable, { useThesisColumns } from '#lib/components/ThesesTable.svelte';
	import type { PublicationSort, ThesisRow, ThesisSortColumn } from '#lib/components/ThesesTable.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { nextSort } from '#lib/sort.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { PUBLICATION_FACETS_ENDPOINT, usePublicationFacets } from '#lib/composables/usePublicationFacets.svelte.js';
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
	const list = useFilteredList<ThesisRow, ReturnType<typeof usePublicationFacets>>({
		filters: FILTERS,
		// Sans filtre de statut, les thèses soutenues et en cours.
		baseParams: () => new URLSearchParams({ doc_type: THESIS_DOC_TYPES }),
		endpoint: '/api/publications',
		itemsKey: 'publications',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		defaultSort: 'soutenance_desc',
		urlSync: () => urlSync,
		basePath: () => basePath,
		facets: (buildParams) => usePublicationFacets({ filters: FILTERS, apiKey: () => `${apiKey}-facets`, buildParams }),
	});

	function toggleSort(column: ThesisSortColumn) {
		const dates: ThesisSortColumn[] = ['inscription', 'soutenance'];
		list.setSort(nextSort(list.sort, column, dates.includes(column) ? 'desc' : 'asc'));
	}

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', list.sort);
		// Colonnes visibles → le CSV reflète le tableau affiché.
		params.set('columns', columns.visibleColumns.join(','));
		return withBase(`/api/publications/export-theses.csv?${paramsToQuery(params)}`);
	}

	onMount(list.restore);
</script>

<ListToolbar bind:search={list.search} placeholder="Rechercher par titre ou sujet" onsearch={list.onSearchInput} list={list.listing} one="thèse" many="thèses" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={THESIS_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={list.facets.sourceCounts} loaded={list.facets.loaded} entityEndpoint={PUBLICATION_FACETS_ENDPOINT} buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}
	<ThesesTable items={list.listing.items} loading={list.listing.loading} error={list.listing.error} sort={list.sort as PublicationSort} onToggleSort={toggleSort} {columns} onopen={drawer.open} activeId={drawer.id} />
	<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>

{#if drawer.id !== null}
	<PublicationDrawer
		publicationId={drawer.id}
		onclose={() => drawer.open(null)}
		onopen={drawer.open}
		onchange={() => {
			list.listing.load();
			list.facets.load();
		}}
	/>
{/if}
