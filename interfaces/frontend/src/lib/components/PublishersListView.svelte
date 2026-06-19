<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import type { Snippet } from 'svelte';

	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import type { components } from '$lib/api/schema';

	type Publisher = components['schemas']['PublisherListItem'];

	// Composant de liste d'éditeurs réutilisable. Utilisé par :
	// - `/publishers` (mode autonome avec sync URL)
	// - `/admin/publishers` (snippet `actionCell` pour Modifier/Fusionner)
	let {
		apiKey = 'publishers-list',
		urlSync = false,
		basePath = '/publishers',
		perPage = 50,
		withPubs = false,
		actionCell,
		actionColumnHeader = '',
	}: {
		apiKey?: string;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Si true, n'expose que les éditeurs avec ≥ 1 publication rattachée
		 *  (mode page publique, masque les orphelines). Défaut false = admin. */
		withPubs?: boolean;
		/** Snippet rendu dans la colonne actions (1 row → 1 cell). */
		actionCell?: Snippet<[Publisher]>;
		actionColumnHeader?: string;
	} = $props();

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('-pubs');
	let selectedPublisherTypes: string[] = $state([]);
	let selectedCountries: string[] = $state([]);

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedPublisherTypes.length) params.set('publisher_type', selectedPublisherTypes.join(','));
		if (selectedCountries.length) params.set('country', selectedCountries.join(','));
		if (withPubs) params.set('with_pubs', 'true');
		return params;
	}

	const publishers = usePaginatedFetch<Publisher>({
		endpoint: '/api/publishers',
		itemsKey: 'publishers',
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
		endpoint: '/api/publishers/facets',
		apiKey: () => `${apiKey}-facets`,
		buildParams: buildFilterParams,
		facets: {
			publisherTypes: { type: 'labeled', apiKey: 'publisher_types' },
			countries: { type: 'labeled', apiKey: 'countries' },
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			selectedPublisherTypes: { type: 'string_array', urlKey: 'publisher_type' },
			selectedCountries: { type: 'string_array', urlKey: 'country' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: '-pubs' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedPublisherTypes,
			selectedCountries,
			search,
			currentSort,
			currentPage: publishers.page,
		}));
	}

	function onFilterChange() {
		publishers.page = 1;
		syncUrl();
		publishers.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(() => {
		publishers.page = 1;
		syncUrl();
		publishers.load();
	});

	function setSort(s: string) {
		currentSort = currentSort === s ? oppositeSort(s) : s;
		publishers.page = 1;
		syncUrl();
		publishers.load();
	}

	function oppositeSort(s: string): string {
		return s.startsWith('-') ? s.slice(1) : '-' + s;
	}

	function sortArrow(col: 'name' | 'journals' | 'pubs'): string {
		if (currentSort === col) return '▲';
		if (currentSort === '-' + col) return '▼';
		return '';
	}

	function publisherTypeLabel(value: string | null): string {
		if (!value) return '';
		const opt = facets.options.publisherTypes.find((o) => o.value === value);
		return opt ? opt.text : value;
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			if (restored.selectedPublisherTypes) selectedPublisherTypes = restored.selectedPublisherTypes as string[];
			if (restored.selectedCountries) selectedCountries = restored.selectedCountries as string[];
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) publishers.page = restored.currentPage as number;
		}
		await facets.load();
		publishers.load();
	});
</script>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="text"
		placeholder="Rechercher dans les noms…"
		bind:value={search}
		oninput={onSearchInput}
	/>
	<FacetDropdown
		label="Types"
		options={facets.options.publisherTypes}
		bind:selected={selectedPublisherTypes}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="Pays"
		options={facets.options.countries}
		searchable
		bind:selected={selectedCountries}
		onchange={onFilterChange}
	/>
	<span class="count">{publishers.total.toLocaleString('fr-FR')} éditeur{publishers.total > 1 ? 's' : ''}</span>
</div>

<div class="table-scroll">
<table class="publishers-table">
	<thead>
		<tr>
			<th class="sortable" onclick={() => setSort('name')}>
				Nom {sortArrow('name')}
			</th>
			<th>Type</th>
			<th>Pays</th>
			<th>Préfixes DOI</th>
			<th class="num sortable" onclick={() => setSort('journals')}>
				Revues {sortArrow('journals')}
			</th>
			<th class="num sortable" onclick={() => setSort('pubs')}>
				Publis {sortArrow('pubs')}
			</th>
			{#if actionCell}<th>{actionColumnHeader}</th>{/if}
		</tr>
	</thead>
	<tbody>
		{#each publishers.items as p (p.id)}
			<tr class:predatory={p.is_predatory}>
				<td>
					<a href="{base}/publishers/{p.id}" class="publisher-link">{p.name}</a>
					{#if p.is_predatory}<span class="badge-pred">prédateur</span>{/if}
				</td>
				<td class="muted">{publisherTypeLabel(p.publisher_type)}</td>
				<td class="muted">{p.country?.toUpperCase() ?? ''}</td>
				<td class="prefixes">
					{#each p.doi_prefixes as dp (dp.prefix)}
						<span class="prefix-chip" title="RA : {dp.ra}{dp.crossref_member_id ? ` / member ${dp.crossref_member_id}` : ''}">{dp.prefix}</span>
					{/each}
				</td>
				<td class="num">{p.journal_count.toLocaleString('fr-FR')}</td>
				<td class="num">{p.pub_count.toLocaleString('fr-FR')}</td>
				{#if actionCell}<td class="actions">{@render actionCell(p)}</td>{/if}
			</tr>
		{/each}
		{#if publishers.items.length === 0}
			<TableStatusRow loading={publishers.loading} colspan={actionCell ? 7 : 6} emptyText="Aucun éditeur ne correspond aux filtres." />
		{/if}
	</tbody>
</table>
</div>

<Pagination
	page={publishers.page}
	pages={publishers.pages}
	onchange={(p) => {
		publishers.page = p;
		syncUrl();
		publishers.load();
	}}
/>

<style>
	.publishers-table {
		width: 100%;
		min-width: 620px;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.publishers-table thead th {
		background: var(--surface);
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.publishers-table thead th.num { text-align: right; }
	.publishers-table thead th.sortable { cursor: pointer; user-select: none; }
	.publishers-table thead th.sortable:hover { color: var(--accent); }
	.publishers-table tbody tr { border-bottom: 1px solid var(--border-subtle); }
	.publishers-table tbody tr:last-child { border-bottom: none; }
	.publishers-table tbody tr:hover { background: var(--surface-hover); }
	.publishers-table tbody tr.predatory td { background: #fff0f0; }
	.publishers-table td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }
	.publishers-table td.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: var(--muted);
	}
	.muted { color: var(--muted); }
	.no-results { text-align: center; color: var(--muted); padding: 30px; }

	.prefixes { display: flex; flex-wrap: wrap; gap: 3px; }
	.prefix-chip {
		background: var(--border-subtle);
		color: var(--muted);
		padding: 1px 6px;
		border-radius: 8px;
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.publisher-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.publisher-link:hover { text-decoration: underline; }
	.badge-pred {
		font-size: 0.7rem;
		padding: 1px 5px;
		background: var(--danger);
		color: white;
		border-radius: 8px;
		margin-left: 6px;
		vertical-align: middle;
		font-weight: 600;
	}
	.actions { white-space: nowrap; position: relative; }
</style>
