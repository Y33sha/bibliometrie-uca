<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { columnLabels } from '#lib/labels.js';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { facetDefs } from '#lib/filterRegistry.js';
	import { MONOGRAPH_FILTER_GROUPS, monographFilters } from '#lib/monographFilters.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import { withBase } from '#lib/paths.js';
	import { paramsToQuery } from '#lib/utils.js';
	import type { components } from '#lib/api/schema.js';

	type Monograph = components['schemas']['MonographListItem'];

	// Liste de monographies réutilisable. Utilisée par :
	// - `/monographs` (filtres reportés dans l'URL)
	// - `/publishers/[id]?tab=monographs` (filtre `publisherId` fixe)
	// - `/journals/[id]?tab=monographs` (filtre `serialId` fixe)
	interface ExternalFilters {
		publisherId?: number;
		serialId?: number;
	}

	let {
		apiKey,
		externalFilters,
		urlSync = false,
		basePath = '/monographs',
	}: {
		apiKey: string;
		externalFilters?: ExternalFilters;
		/** Reporte filtres, tri et page dans l'URL de `basePath`. */
		urlSync?: boolean;
		basePath?: string;
	} = $props();

	// Éditeur ou collection imposés par la page : la colonne porte la même valeur sur toutes les lignes, et est masquée.
	const publisherFixed = $derived(externalFilters?.publisherId != null);
	const serialFixed = $derived(externalFilters?.serialId != null);
	const columnCount = $derived(7 - Number(publisherFixed) - Number(serialFixed));

	// svelte-ignore state_referenced_locally
	const FILTERS = monographFilters(externalFilters?.publisherId, externalFilters?.serialId);

	const list = useFilteredList<Monograph, ReturnType<typeof useFacets>>({
		filters: FILTERS,
		endpoint: '/api/monographs',
		itemsKey: 'monographs',
		perPage: 50,
		apiKey: () => apiKey,
		defaultSort: 'publications_desc',
		urlSync: () => urlSync,
		basePath: () => basePath,
		facets: (buildParams) =>
			useFacets({
				endpoint: '/api/monographs/facets',
				apiKey: () => `${apiKey}-facets`,
				buildParams,
				facets: facetDefs(FILTERS),
			}),
	});

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', list.sort);
		return withBase(`/api/monographs/export.csv?${paramsToQuery(params)}`);
	}

	function setSort(column: 'title' | 'year' | 'publications') {
		list.setSort(nextSort(list.sort, column, column === 'title' ? 'asc' : 'desc'));
	}

	onMount(list.restore);
</script>

<ListToolbar bind:search={list.search} placeholder="Rechercher par titre ou ISBN" onsearch={list.onSearchInput} list={list.listing} one="monographie" many="monographies" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={MONOGRAPH_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={{}} loaded={list.facets.loaded} entityEndpoint="/api/monographs/facets" buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}

<TableScroll>
	<table class="data-table monographs-table">
		<thead>
			<tr>
				<th class="sortable" onclick={() => setSort('title')}>{columnLabels.title} <SortChevron direction={sortDirection(list.sort, 'title')} /></th>
				<th>{columnLabels.type}</th>
				<th class="num sortable" onclick={() => setSort('year')}>{columnLabels.year} <SortChevron direction={sortDirection(list.sort, 'year')} /></th>
				<th>ISBN</th>
				{#if !publisherFixed}<th>{columnLabels.publisher}</th>{/if}
				{#if !serialFixed}<th>Collection</th>{/if}
				<th class="num sortable" onclick={() => setSort('publications')}>{columnLabels.publications} <SortChevron direction={sortDirection(list.sort, 'publications')} /></th>
			</tr>
		</thead>
		<tbody>
			{#each list.listing.items as m (m.id)}
				<tr>
					<td><a href={resolve(`monographs/${m.id}`)}><PublicationTitle titre={m.title} /></a></td>
					<td class="muted">{m.proceedings ? 'Actes' : 'Livre'}</td>
					<td class="num">{m.year ?? ''}</td>
					<td><div class="tag-list">{#each [m.isbn, m.eisbn].filter(Boolean) as isbn (isbn)}<span class="tag id-badge">{isbn}</span>{/each}</div></td>
					{#if !publisherFixed}
						<td>
							{#if m.publisher_id}<a href={resolve(`publishers/${m.publisher_id}`)}>{m.publisher_name}</a>{/if}
						</td>
					{/if}
					{#if !serialFixed}
						<td>
							{#if m.serial_id}<a href={resolve(`journals/${m.serial_id}`)}>{m.journal_title}</a>{/if}
						</td>
					{/if}
					<td class="num">{m.publication_count.toLocaleString('fr-FR')}</td>
				</tr>
			{/each}
			{#if list.listing.items.length === 0}
				<TableStatusRow loading={list.listing.loading} error={list.listing.error} colspan={columnCount} emptyText="Aucune monographie ne correspond aux filtres." />
			{/if}
		</tbody>
	</table>
</TableScroll>

<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>

<style>
	.monographs-table { min-width: 720px; }
</style>
