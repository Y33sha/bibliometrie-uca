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
	import IconButton from '#lib/components/IconButton.svelte';
	import PublisherDrawer from '#lib/components/publishers/PublisherDrawer.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { facetDefs } from '#lib/filterRegistry.js';
	import { PUBLISHER_FILTER_GROUPS, PUBLISHER_FILTERS } from '#lib/publisherFilters.js';
	import { crossrefMemberIds } from '#lib/sources.svelte.js';
	import IdentifierLink from '#lib/components/IdentifierLink.svelte';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import { withBase } from '#lib/paths.js';
	import { paramsToQuery } from '#lib/utils.js';
	import type { components } from '#lib/api/schema.js';

	type Publisher = components['schemas']['PublisherListItem'];

	// Liste des éditeurs de la page `/publishers`. La session admin y gagne la facette « Publications » et, en tête de ligne, l'icône du volet d'édition de l'éditeur.
	let {
		apiKey = 'publishers-list',
		urlSync = false,
		basePath = '/publishers',
		perPage = 50,
	}: {
		apiKey?: string;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
	} = $props();

	// Volet d'édition d'un éditeur, en session admin : ouvert tant que `?publisher=<id>` figure dans l'URL.
	const drawer = useDrawerParam('publisher', isAdmin);

	const list = useFilteredList<Publisher, ReturnType<typeof useFacets>>({
		filters: PUBLISHER_FILTERS,
		endpoint: '/api/publishers',
		itemsKey: 'publishers',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		defaultSort: 'publications_desc',
		urlSync: () => urlSync,
		basePath: () => basePath,
		facets: (buildParams) =>
			useFacets({
				endpoint: '/api/publishers/facets',
				apiKey: () => `${apiKey}-facets`,
				buildParams,
				facets: facetDefs(PUBLISHER_FILTERS),
			}),
	});

	function setSort(column: 'name' | 'serials' | 'publications') {
		list.setSort(nextSort(list.sort, column, column === 'name' ? 'asc' : 'desc'));
	}

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', list.sort);
		return withBase(`/api/publishers/export.csv?${paramsToQuery(params)}`);
	}

	// Un type inconnu est une valeur absente : la cellule reste vide.
	function publisherTypeLabel(value: string | null): string {
		if (!value || value === 'unknown') return '';
		const opt = list.facets.options.publisherTypes?.find((o) => o.value === value);
		return opt ? opt.text : value;
	}

	onMount(list.restore);
</script>

<ListToolbar bind:search={list.search} placeholder="Rechercher dans les noms" onsearch={list.onSearchInput} list={list.listing} one="éditeur" many="éditeurs" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={PUBLISHER_FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={PUBLISHER_FILTERS} groups={PUBLISHER_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={{}} loaded={list.facets.loaded} entityEndpoint="/api/publishers/facets" buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}
<TableScroll>
<table class="data-table publishers-table">
	<thead>
		<tr>
			{#if isAdmin()}<th class="row-actions"></th>{/if}
			<th class="sortable" onclick={() => setSort('name')}>
				Nom <SortChevron direction={sortDirection(list.sort, 'name')} />
			</th>
			<th>Identifiants</th>
			<th>{columnLabels.type}</th>
			<th>{columnLabels.country}</th>
			<th>Préfixes DOI</th>
			<th class="num sortable" onclick={() => setSort('serials')}>
				Publications en série <SortChevron direction={sortDirection(list.sort, 'serials')} />
			</th>
			<th class="num sortable" onclick={() => setSort('publications')}>
				{columnLabels.publications} <SortChevron direction={sortDirection(list.sort, 'publications')} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#each list.listing.items as p (p.id)}
			<tr class:active-row={p.id === drawer.id}>
				{#if isAdmin()}
					<td class="row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(p.id)} />
					</td>
				{/if}
				<td>
					<a href={resolve(`publishers/${p.id}`)} class="entity-link">{p.name}</a>
				</td>
				<!-- Un emplacement vide aligne les membres Crossref d'une ligne à l'autre. -->
				<td>
					<span class="publisher-ids">
						{#if p.openalex_id}<IdentifierLink id_type="openalex" id_value={p.openalex_id} />{:else}<span class="logo-icon logo-identifier logo-placeholder"></span>{/if}
						{#each crossrefMemberIds(p.doi_prefixes) as member (member)}<IdentifierLink id_type="crossref_member" id_value={String(member)} />{/each}
					</span>
				</td>
				<td class="muted">{publisherTypeLabel(p.publisher_type)}</td>
				<td class="muted">{p.country?.toUpperCase() ?? ''}</td>
				<td>
					<div class="tag-list">
						{#each p.doi_prefixes as dp (dp.prefix)}
							<span class="tag id-badge" title="RA : {dp.ra}{dp.crossref_member_id ? ` / member ${dp.crossref_member_id}` : ''}">{dp.prefix}</span>
						{/each}
					</div>
				</td>
				<!-- Un décompte non nul mène à l'onglet correspondant de la fiche. -->
				<td class="num">{#if p.serial_count}<a href={resolve(`publishers/${p.id}?tab=serials`)}>{p.serial_count.toLocaleString('fr-FR')}</a>{:else}0{/if}</td>
				<td class="num">{#if p.publication_count}<a href={resolve(`publishers/${p.id}?tab=publications`)}>{p.publication_count.toLocaleString('fr-FR')}</a>{:else}0{/if}</td>
			</tr>
		{/each}
		{#if list.listing.items.length === 0}
			<TableStatusRow loading={list.listing.loading} error={list.listing.error} colspan={isAdmin() ? 8 : 7} emptyText="Aucun éditeur ne correspond aux filtres." />
		{/if}
	</tbody>
</table>
</TableScroll>

<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>

{#if drawer.id !== null}
	<PublisherDrawer
		id={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={() => {
			list.listing.load();
			list.facets.load();
		}}
	/>
{/if}

<style>
	.publishers-table { min-width: 620px; }
	.publishers-table td.num { color: var(--muted); }

	.publisher-ids { display: inline-flex; gap: 4px; align-items: center; white-space: nowrap; }
</style>
