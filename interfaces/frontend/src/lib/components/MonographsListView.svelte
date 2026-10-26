<script lang="ts">
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { autofocus } from '#lib/actions/focus.js';
	import EntityFilter from '#lib/components/EntityFilter.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
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

	const KIND_LABELS: Record<string, string> = { book: 'Livres', proceedings: "Volumes d'actes" };

	let search = $state('');
	let selectedKinds: string[] = $state([]);
	let selectedYears: string[] = $state([]);
	let selectedPublisher: string[] = $state([]); // 0 ou 1 identifiant d'éditeur
	let selectedSerial: string[] = $state([]); // 0 ou 1 identifiant de collection
	let currentSort = $state('publications_desc');

	// Paramètres partagés par la liste et ses facettes : les décomptes suivent la recherche.
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		const publisherId = externalFilters?.publisherId != null ? String(externalFilters.publisherId) : selectedPublisher[0];
		if (publisherId) params.set('publisher_id', publisherId);
		const serialId = externalFilters?.serialId != null ? String(externalFilters.serialId) : selectedSerial[0];
		if (serialId) params.set('serial_id', serialId);
		if (selectedKinds.length) params.set('type', selectedKinds.join(','));
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		const q = search.trim();
		if (q) params.set('search', q);
		return params;
	}

	const monographs = usePaginatedFetch<Monograph>({
		endpoint: '/api/monographs',
		itemsKey: 'monographs',
		perPage: 50,
		apiKey: () => apiKey,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/monographs/facets',
		apiKey: () => `${apiKey}-facets`,
		buildParams: buildFilterParams,
		facets: {
			kinds: { type: 'label_map', apiKey: 'kinds', labels: KIND_LABELS },
			years: { type: 'simple', apiKey: 'years' },
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			selectedKinds: { type: 'string_array', urlKey: 'type' },
			selectedYears: { type: 'string_array', urlKey: 'year' },
			selectedPublisher: { type: 'string_array', urlKey: 'publisher_id' },
			selectedSerial: { type: 'string_array', urlKey: 'serial_id' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'publications_desc' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedKinds,
			selectedYears,
			selectedPublisher,
			selectedSerial,
			search,
			currentSort,
			currentPage: monographs.page,
		}));
	}

	function onFilterChange() {
		monographs.page = 1;
		syncUrl();
		monographs.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(onFilterChange);

	function setSort(column: 'title' | 'year' | 'publications') {
		currentSort = nextSort(currentSort, column, column === 'title' ? 'asc' : 'desc');
		monographs.page = 1;
		syncUrl();
		monographs.load();
	}

	onMount(() => {
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			if (restored.selectedKinds) selectedKinds = restored.selectedKinds as string[];
			if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
			if (restored.selectedPublisher) selectedPublisher = restored.selectedPublisher as string[];
			if (restored.selectedSerial) selectedSerial = restored.selectedSerial as string[];
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) monographs.page = restored.currentPage as number;
		}
		facets.load();
		monographs.load();
	});
</script>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="search"
		class="search"
		placeholder="Rechercher par titre ou ISBN…"
		bind:value={search}
		use:autofocus
		onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }}
		oninput={onSearchInput}
	/>
	<FacetDropdown label="Types" options={facets.options.kinds} bind:selected={selectedKinds} onchange={onFilterChange} />
	<FacetDropdown label="Années" allLabel="Toutes" options={facets.options.years} searchable bind:selected={selectedYears} onchange={onFilterChange} />
	{#if !publisherFixed}
		<EntityFilter
			label="Éditeur"
			endpoint="/api/monographs/facets"
			kind="publisher"
			buildParams={buildFilterParams}
			selected={selectedPublisher}
			onchange={(ids) => { selectedPublisher = ids; onFilterChange(); }}
		/>
	{/if}
	{#if !serialFixed}
		<EntityFilter
			label="Collection"
			endpoint="/api/monographs/facets"
			kind="serial"
			buildParams={buildFilterParams}
			selected={selectedSerial}
			onchange={(ids) => { selectedSerial = ids; onFilterChange(); }}
		/>
	{/if}
	<span class="count">{monographs.total.toLocaleString('fr-FR')} monographie{monographs.total > 1 ? 's' : ''}</span>
</div>

<div class="table-scroll">
	<table class="data-table monographs-table">
		<thead>
			<tr>
				<th class="sortable" onclick={() => setSort('title')}>Titre <SortChevron direction={sortDirection(currentSort, 'title')} /></th>
				<th>Type</th>
				<th class="num sortable" onclick={() => setSort('year')}>Année <SortChevron direction={sortDirection(currentSort, 'year')} /></th>
				<th>ISBN</th>
				{#if !publisherFixed}<th>Éditeur</th>{/if}
				{#if !serialFixed}<th>Collection</th>{/if}
				<th class="num sortable" onclick={() => setSort('publications')}>Publis <SortChevron direction={sortDirection(currentSort, 'publications')} /></th>
			</tr>
		</thead>
		<tbody>
			{#each monographs.items as m (m.id)}
				<tr>
					<td><a href={resolve(`monographs/${m.id}`)}><PublicationTitle titre={m.title} /></a></td>
					<td class="muted">{m.proceedings ? 'Actes' : 'Livre'}</td>
					<td class="num">{m.year ?? ''}</td>
					<td class="isbn">{[m.isbn, m.eisbn].filter(Boolean).join(' / ')}</td>
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
			{#if monographs.items.length === 0}
				<TableStatusRow loading={monographs.loading} error={monographs.error} colspan={columnCount} emptyText="Aucune monographie ne correspond aux filtres." />
			{/if}
		</tbody>
	</table>
</div>

<Pagination
	page={monographs.page}
	pages={monographs.pages}
	onchange={(p) => {
		monographs.page = p;
		syncUrl();
		monographs.load();
	}}
/>


<style>
	.monographs-table { min-width: 720px; }
	.isbn { font-family: var(--mono); font-size: 0.8rem; white-space: nowrap; }
	.muted { color: var(--muted); }
	.search { width: 22rem; max-width: 100%; }
</style>
