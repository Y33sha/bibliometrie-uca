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
	import type { PresenceItem } from '#lib/components/filters/PresenceOptions.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import SerialDrawer from '#lib/components/serials/SerialDrawer.svelte';
	import IssnBadge from '#lib/components/serials/IssnBadge.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import { withBase } from '#lib/paths.js';
	import { paramsToQuery } from '#lib/utils.js';
	import { facetDefs, type PresenceCounts } from '#lib/filterRegistry.js';
	import { SERIAL_FILTER_GROUPS, serialFilters } from '#lib/serialFilters.js';
	import type { components } from '#lib/api/schema.js';

	type Serial = components['schemas']['SerialListItem'];
	type SerialListFacet = components['schemas']['SerialListFacet'];

	// Composant de liste de publications en série réutilisable. Utilisé par :
	// - `/journals` (mode autonome avec sync URL)
	// - `/publishers/[id]?tab=journals` (filtre `publisherId` fixe)
	// La session admin gagne, en tête de ligne, l'icône du volet d'édition de la publication en série ; sur `/journals`, elle gagne aussi la facette « Publications ».
	interface ExternalFilters {
		publisherId?: number;
	}

	let {
		apiKey = 'journals-list',
		externalFilters,
		urlSync = false,
		basePath = '/journals',
		perPage = 50,
		onchange,
	}: {
		apiKey?: string;
		externalFilters?: ExternalFilters;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Appelé après chaque écriture du volet, après le rechargement de la liste. */
		onchange?: () => void;
	} = $props();

	// Volet d'édition d'une publication en série, en session admin : ouvert tant que `?serial=<id>` figure dans l'URL.
	const drawer = useDrawerParam('serial', isAdmin);

	// Éditeur imposé par le contexte : la facette et la colonne Éditeur portent alors la même valeur sur toutes les lignes, et sont masquées.
	const publisherFixed = $derived(externalFilters?.publisherId != null);

	// Listes et classements servis par les décomptes, avec leurs niveaux, et les décomptes de chaque liste et de chaque niveau.
	let listItems: PresenceItem[] = $state([]);
	let listCounts: PresenceCounts = $state({});

	// svelte-ignore state_referenced_locally
	const FILTERS = serialFilters(externalFilters?.publisherId, () => listItems);

	const list = useFilteredList<Serial, ReturnType<typeof useFacets>>({
		filters: FILTERS,
		endpoint: '/api/serials',
		itemsKey: 'serials',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		defaultSort: 'publications_desc',
		urlSync: () => urlSync,
		basePath: () => basePath,
		facets: (buildParams) =>
			useFacets({
				endpoint: '/api/serials/facets',
				apiKey: () => `${apiKey}-facets`,
				buildParams,
				facets: facetDefs(FILTERS),
				afterLoad(data) {
					const lists = (data.lists ?? []) as SerialListFacet[];
					listItems = lists.map((l) => ({
						key: l.code,
						label: l.label,
						levels: l.levels.map((level) => ({ key: level.code, label: level.label })),
					}));
					listCounts = Object.fromEntries(
						lists.flatMap((l) => {
							const total = l.count + l.absent_count;
							return [
								[l.code, { yes: l.count, no: l.absent_count }],
								...l.levels.map((level) => [level.code, { yes: level.count, no: total - level.count }]),
							];
						}),
					);
				},
			}),
	});

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', list.sort);
		return withBase(`/api/serials/export.csv?${paramsToQuery(params)}`);
	}

	function setSort(column: 'title' | 'publisher' | 'publications') {
		list.setSort(nextSort(list.sort, column, column === 'publications' ? 'desc' : 'asc'));
	}

	function serialTypeLabel(value: string | null): string {
		if (!value) return '';
		const opt = list.facets.options.serialTypes?.find((o) => o.value === value);
		return opt ? opt.text : value;
	}

	onMount(list.restore);
</script>

<ListToolbar bind:search={list.search} placeholder="Rechercher par titre ou ISSN" onsearch={list.onSearchInput} list={list.listing} one="publication en série" many="publications en série" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={SERIAL_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={listCounts} loaded={list.facets.loaded} entityEndpoint="/api/serials/facets" buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}
<TableScroll>
<table class="data-table journals-table">
	<thead>
		<tr>
			{#if isAdmin()}<th class="row-actions"></th>{/if}
			<th class="diamond-col" aria-label="Revue diamant"></th>
			<th class="sortable" onclick={() => setSort('title')}>
				{columnLabels.title} <SortChevron direction={sortDirection(list.sort, 'title')} />
			</th>
			<th>ISSN</th>
			{#if !publisherFixed}
				<th class="sortable" onclick={() => setSort('publisher')}>
					{columnLabels.publisher} <SortChevron direction={sortDirection(list.sort, 'publisher')} />
				</th>
			{/if}
			<th>{columnLabels.type}</th>
			<th class="num sortable" onclick={() => setSort('publications')}>
				{columnLabels.publications} <SortChevron direction={sortDirection(list.sort, 'publications')} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#each list.listing.items as j (j.id)}
			<tr class:active-row={j.id === drawer.id}>
				{#if isAdmin()}
					<td class="row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(j.id)} />
					</td>
				{/if}
				<td class="diamond-col">
					{#if j.oa_model === 'diamond'}
						<span class="diamond" title="Revue diamant&nbsp;: open access sans frais de publication" aria-label="Revue diamant">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
								<path d="M6 3h12l4 6-10 13L2 9Z" />
								<path d="M11 3 8 9l4 13 4-13-3-6" />
								<path d="M2 9h20" />
							</svg>
						</span>
					{/if}
				</td>
				<td>
					<a href={resolve(`journals/${j.id}`)} class="entity-link">{j.title}</a>
					{#if j.is_in_doaj}
						{#if j.doaj_url}
							<a class="tag tag-success badge-doaj" href={j.doaj_url} target="_blank" rel="noopener" title="Fiche DOAJ (nouvel onglet)">DOAJ</a>
						{:else}
							<span class="tag tag-success badge-doaj" title="Indexée dans DOAJ">DOAJ</span>
						{/if}
					{/if}				</td>
				<td><div class="tag-list">{#each j.issns as issn (issn)}<IssnBadge {issn} />{/each}</div></td>
				{#if !publisherFixed}
					<td class="muted">
						{#if j.publisher_name}
							{#if j.publisher_id}
								<a href={resolve(`publishers/${j.publisher_id}`)}>{j.publisher_name}</a>
							{:else}
								{j.publisher_name}
							{/if}
						{/if}
					</td>
				{/if}
				<td class="muted">{serialTypeLabel(j.serial_type)}</td>
				<td class="num">{j.publication_count.toLocaleString('fr-FR')}</td>
			</tr>
		{/each}
		{#if list.listing.items.length === 0}
			<TableStatusRow loading={list.listing.loading} error={list.listing.error} colspan={(publisherFixed ? 5 : 6) + (isAdmin() ? 1 : 0)} emptyText="Aucune publication en série ne correspond aux filtres." />
		{/if}
	</tbody>
</table>
</TableScroll>

<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>

{#if drawer.id !== null}
	<SerialDrawer
		id={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={() => {
			list.listing.load();
			list.facets.load();
			onchange?.();
		}}
	/>
{/if}

<style>
	.journals-table { min-width: 660px; }
	.journals-table td.num { color: var(--muted); }
	.diamond-col { width: 1.5rem; padding-right: 0; }
	.diamond { display: inline-flex; color: var(--diamond-text); vertical-align: middle; }
</style>
