<script lang="ts">
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { asset, resolve } from '$app/paths';
	import type { Snippet } from 'svelte';

	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { crossrefMemberIds, crossrefMemberUrl } from '#lib/sources.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import type { components } from '#lib/api/schema.js';

	type Publisher = components['schemas']['PublisherListItem'];

	// Liste des éditeurs de la page `/publishers`. La session admin y gagne la facette « Publications » et la colonne d'actions que lui passe la page.
	let {
		apiKey = 'publishers-list',
		urlSync = false,
		basePath = '/publishers',
		perPage = 50,
		actionCell,
		actionColumnHeader = '',
	}: {
		apiKey?: string;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Snippet rendu dans la colonne actions (1 row → 1 cell). */
		actionCell?: Snippet<[Publisher]>;
		actionColumnHeader?: string;
	} = $props();

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('publications_desc');
	let selectedPublisherTypes: string[] = $state([]);
	let selectedCountries: string[] = $state([]);
	// Éditeurs avec ou sans publication du périmètre. Par défaut, ceux qui en ont ; seule la session admin change ce réglage.
	let selectedPublications: string[] = $state(['yes']);

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedPublisherTypes.length) params.set('publisher_type', selectedPublisherTypes.join(','));
		if (selectedCountries.length) params.set('country', selectedCountries.join(','));
		if (selectedPublications.length === 1) params.set('has_publications', selectedPublications[0]);
		return params;
	}

	const publishers = usePaginatedFetch<Publisher>({
		endpoint: '/api/publishers',
		itemsKey: 'publishers',
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
		endpoint: '/api/publishers/facets',
		apiKey: () => `${apiKey}-facets`,
		// Inclut le terme de recherche pour que les comptes de facettes suivent le champ de recherche (comme la liste).
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
		facets: {
			publisherTypes: { type: 'labeled', apiKey: 'publisher_types' },
			countries: { type: 'labeled', apiKey: 'countries' },
			publications: { type: 'boolean', apiKey: 'publications', yesLabel: 'Avec', noLabel: 'Sans' },
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			selectedPublisherTypes: { type: 'string_array', urlKey: 'publisher_type' },
			selectedCountries: { type: 'string_array', urlKey: 'country' },
			hasPublications: { type: 'single', urlKey: 'has_publications', defaultValue: 'yes' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'publications_desc' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedPublisherTypes,
			selectedCountries,
			hasPublications: selectedPublications.length === 1 ? selectedPublications[0] : 'all',
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
		facets.load();
	});

	function setSort(column: 'name' | 'serials' | 'publications') {
		currentSort = nextSort(currentSort, column, column === 'name' ? 'asc' : 'desc');
		publishers.page = 1;
		syncUrl();
		publishers.load();
	}

	function publisherTypeLabel(value: string | null): string {
		if (!value) return '';
		const opt = facets.options.publisherTypes.find((o) => o.value === value);
		return opt ? opt.text : value;
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			if (restored.selectedPublisherTypes) selectedPublisherTypes = restored.selectedPublisherTypes as string[];
			if (restored.selectedCountries) selectedCountries = restored.selectedCountries as string[];
			if (restored.hasPublications != null && isAdmin()) {
				const value = restored.hasPublications as string;
				selectedPublications = value === 'all' ? [] : [value];
			}
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
		type="search"
		placeholder="Rechercher dans les noms…"
		bind:value={search}
		onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }}
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
	{#if isAdmin()}
		<FacetDropdown
			label="Publications"
			options={facets.options.publications}
			bind:selected={selectedPublications}
			onchange={onFilterChange}
		/>
	{/if}
	<span class="count">{publishers.total.toLocaleString('fr-FR')} éditeur{publishers.total > 1 ? 's' : ''}</span>
</div>

<div class="table-scroll">
<table class="data-table publishers-table">
	<thead>
		<tr>
			<th class="sortable" onclick={() => setSort('name')}>
				Nom <SortChevron direction={sortDirection(currentSort, 'name')} />
			</th>
			<th>Type</th>
			<th>Pays</th>
			<th>Préfixes DOI</th>
			<th class="num sortable" onclick={() => setSort('serials')}>
				Publications en série <SortChevron direction={sortDirection(currentSort, 'serials')} />
			</th>
			<th class="num sortable" onclick={() => setSort('publications')}>
				Publis <SortChevron direction={sortDirection(currentSort, 'publications')} />
			</th>
			{#if actionCell}<th>{actionColumnHeader}</th>{/if}
		</tr>
	</thead>
	<tbody>
		{#each publishers.items as p (p.id)}
			<tr>
				<td>
					<a href={resolve(`publishers/${p.id}`)} class="entity-link">{p.name}</a>
					{#each crossrefMemberIds(p.doi_prefixes) as member (member)}
						<a
							class="crossref-link"
							href={crossrefMemberUrl(member)}
							target="_blank"
							rel="noopener"
							title="Membre Crossref {member} (nouvel onglet)"
						>
							<img src={asset('icons/crossref.ico')} alt="Crossref" width="14" height="14" />
						</a>
					{/each}
				</td>
				<td class="muted">{publisherTypeLabel(p.publisher_type)}</td>
				<td class="muted">{p.country?.toUpperCase() ?? ''}</td>
				<td class="prefixes">
					{#each p.doi_prefixes as dp (dp.prefix)}
						<span class="prefix-chip" title="RA : {dp.ra}{dp.crossref_member_id ? ` / member ${dp.crossref_member_id}` : ''}">{dp.prefix}</span>
					{/each}
				</td>
				<td class="num">{p.serial_count.toLocaleString('fr-FR')}</td>
				<td class="num">{p.publication_count.toLocaleString('fr-FR')}</td>
				{#if actionCell}<td class="actions row-actions">{@render actionCell(p)}</td>{/if}
			</tr>
		{/each}
		{#if publishers.items.length === 0}
			<TableStatusRow loading={publishers.loading} error={publishers.error} colspan={actionCell ? 7 : 6} emptyText="Aucun éditeur ne correspond aux filtres." />
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
	.publishers-table { min-width: 620px; }
	.publishers-table td.num { color: var(--muted); }
	.muted { color: var(--muted); }

	.crossref-link { text-decoration: none; margin-left: 5px; vertical-align: text-bottom; }
	.prefixes { display: flex; flex-wrap: wrap; gap: 3px; }
	.prefix-chip {
		background: var(--border-subtle);
		color: var(--muted);
		padding: 1px 6px;
		border-radius: var(--radius);
		font-size: 0.75rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.actions { white-space: nowrap; position: relative; }
</style>
