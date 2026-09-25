<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { autofocus } from '$lib/actions/focus';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import type { components } from '$lib/api/schema';

	type Monograph = components['schemas']['MonographListItem'];

	// Liste de monographies réutilisable. Utilisée par :
	// - `/monographs` et `/admin/monographs` (filtres reportés dans l'URL)
	// - `/publishers/[id]?tab=monographs` (filtre `publisherId` fixe)
	// - `/journals/[id]?tab=monographs` (filtre `journalId` fixe)
	interface ExternalFilters {
		publisherId?: number;
		journalId?: number;
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
	const journalFixed = $derived(externalFilters?.journalId != null);
	const columnCount = $derived(7 - Number(publisherFixed) - Number(journalFixed));

	const KIND_LABELS: Record<string, string> = { book: 'Livres', proceedings: "Volumes d'actes" };

	let search = $state('');
	let selectedKinds: string[] = $state([]);
	let currentSort = $state('pubs_desc');

	// Paramètres partagés par la liste et ses facettes : les décomptes suivent la recherche.
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (externalFilters?.publisherId != null) params.set('publisher_id', String(externalFilters.publisherId));
		if (externalFilters?.journalId != null) params.set('journal_id', String(externalFilters.journalId));
		if (selectedKinds.length) params.set('kind', selectedKinds.join(','));
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
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			selectedKinds: { type: 'string_array', urlKey: 'kind' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'pubs_desc' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({ selectedKinds, search, currentSort, currentPage: monographs.page }));
	}

	function onFilterChange() {
		monographs.page = 1;
		syncUrl();
		monographs.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(onFilterChange);

	function setSort(column: 'title' | 'year' | 'pubs') {
		currentSort = currentSort === `${column}_desc` ? `${column}_asc` : `${column}_desc`;
		monographs.page = 1;
		syncUrl();
		monographs.load();
	}

	function sortArrow(column: 'title' | 'year' | 'pubs'): string {
		if (currentSort === `${column}_asc`) return '▲';
		if (currentSort === `${column}_desc`) return '▼';
		return '';
	}

	onMount(() => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			if (restored.selectedKinds) selectedKinds = restored.selectedKinds as string[];
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
	<span class="count">{monographs.total.toLocaleString('fr-FR')} monographie{monographs.total > 1 ? 's' : ''}</span>
</div>

<div class="table-scroll">
	<table class="monographs-table">
		<thead>
			<tr>
				<th class="sortable" onclick={() => setSort('title')}>Titre {sortArrow('title')}</th>
				<th>Type</th>
				<th class="num sortable" onclick={() => setSort('year')}>Année {sortArrow('year')}</th>
				<th>ISBN</th>
				{#if !publisherFixed}<th>Éditeur</th>{/if}
				{#if !journalFixed}<th>Collection</th>{/if}
				<th class="num sortable" onclick={() => setSort('pubs')}>Publis {sortArrow('pubs')}</th>
			</tr>
		</thead>
		<tbody>
			{#each monographs.items as m (m.id)}
				<tr>
					<td><a href="{base}/monographs/{m.id}">{m.title}</a></td>
					<td class="muted">{m.proceedings ? 'Actes' : 'Livre'}</td>
					<td class="num">{m.year ?? ''}</td>
					<td class="isbn">{[m.isbn, m.eisbn].filter(Boolean).join(' / ')}</td>
					{#if !publisherFixed}
						<td>
							{#if m.publisher_id}<a href="{base}/publishers/{m.publisher_id}">{m.pub_name}</a>{/if}
						</td>
					{/if}
					{#if !journalFixed}
						<td>
							{#if m.journal_id}<a href="{base}/journals/{m.journal_id}">{m.journal_title}</a>{/if}
						</td>
					{/if}
					<td class="num">{m.pub_count.toLocaleString('fr-FR')}</td>
				</tr>
			{/each}
			{#if monographs.items.length === 0}
				<TableStatusRow loading={monographs.loading} colspan={columnCount} emptyText="Aucune monographie ne correspond aux filtres." />
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
	.monographs-table {
		width: 100%;
		min-width: 720px;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.monographs-table thead th {
		background: var(--surface);
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.monographs-table thead th.num { text-align: right; }
	.monographs-table thead th.sortable { cursor: pointer; user-select: none; }
	.monographs-table thead th.sortable:hover { color: var(--accent); }
	.monographs-table tbody tr { border-bottom: 1px solid var(--border-subtle); }
	.monographs-table tbody tr:last-child { border-bottom: none; }
	.monographs-table td { padding: 6px 10px; font-size: 0.9rem; vertical-align: top; }
	.monographs-table td.num { text-align: right; white-space: nowrap; }
	.isbn { font-family: var(--mono, monospace); font-size: 0.8rem; white-space: nowrap; }
	.muted { color: var(--muted); }
	.search { width: 22rem; max-width: 100%; }
</style>
