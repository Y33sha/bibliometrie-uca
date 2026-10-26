<script lang="ts">
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import type { Snippet } from 'svelte';

	import EntityFilter from '#lib/components/EntityFilter.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import type { components } from '#lib/api/schema.js';

	type Serial = components['schemas']['SerialListItem'];

	// Composant de liste de publications en série réutilisable. Utilisé par :
	// - `/journals` (mode autonome avec sync URL ; la session admin y reçoit le snippet `actionCell` pour Modifier/Fusionner)
	// - `/publishers/[id]?tab=journals` (filtre `publisherId` fixe)
	// La session admin y gagne la facette « Publications ».
	interface ExternalFilters {
		publisherId?: number;
	}

	let {
		apiKey = 'journals-list',
		externalFilters,
		urlSync = false,
		basePath = '/journals',
		perPage = 50,
		actionCell,
		actionColumnHeader = '',
	}: {
		apiKey?: string;
		externalFilters?: ExternalFilters;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Snippet rendu dans la colonne actions (1 row → 1 cell). Si fourni, une colonne Actions est ajoutée à droite du tableau. */
		actionCell?: Snippet<[Serial]>;
		/** En-tête de la colonne actions (vide par défaut, comme admin). */
		actionColumnHeader?: string;
	} = $props();

	// Éditeur imposé par le contexte : la facette et la colonne Éditeur portent alors la même valeur sur toutes les lignes, et sont masquées.
	const publisherFixed = $derived(externalFilters?.publisherId != null);

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('publications_desc');
	let selectedPublisher: string[] = $state([]); // 0 ou 1 identifiant d'éditeur
	let selectedSerialTypes: string[] = $state([]);
	let selectedOaModels: string[] = $state([]);
	let selectedDoaj: string[] = $state([]); // 'true' / 'false'
	// Publications en série avec ou sans publication. Par défaut, celles qui en ont ; seule la session admin change ce réglage.
	let selectedPublications: string[] = $state(['yes']);

	// --- Params builder partagé entre la liste et ses facettes ---
	// Le terme de recherche en fait partie : les décomptes des facettes suivent ainsi le champ de recherche, comme la liste.
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		const publisherId = externalFilters?.publisherId != null
			? String(externalFilters.publisherId)
			: selectedPublisher[0];
		if (publisherId) params.set('publisher_id', publisherId);
		if (selectedSerialTypes.length) params.set('serial_type', selectedSerialTypes.join(','));
		if (selectedOaModels.length) params.set('oa_model', selectedOaModels.join(','));
		// DOAJ : un seul ['true'] / ['false'] est interprétable côté API (bool unique). Les autres cas (vide, ou les 2) = pas de filtre.
		if (selectedDoaj.length === 1) params.set('is_in_doaj', selectedDoaj[0]);
		if (selectedPublications.length === 1) params.set('has_publications', selectedPublications[0]);
		const q = search.trim();
		if (q) params.set('search', q);
		return params;
	}

	const serials = usePaginatedFetch<Serial>({
		endpoint: '/api/serials',
		itemsKey: 'serials',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/serials/facets',
		apiKey: () => `${apiKey}-facets`,
		buildParams: buildFilterParams,
		facets: {
			serialTypes: { type: 'labeled', apiKey: 'serial_types' },
			oaModels: { type: 'labeled', apiKey: 'oa_models' },
			doaj: { type: 'labeled', apiKey: 'doaj' },
			publications: { type: 'boolean', apiKey: 'publications', yesLabel: 'Avec', noLabel: 'Sans' },
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			selectedPublisher: { type: 'string_array', urlKey: 'publisher_id' },
			selectedSerialTypes: { type: 'string_array', urlKey: 'serial_type' },
			selectedOaModels: { type: 'string_array', urlKey: 'oa_model' },
			selectedDoaj: { type: 'string_array', urlKey: 'is_in_doaj' },
			hasPublications: { type: 'single', urlKey: 'has_publications', defaultValue: 'yes' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'publications_desc' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedPublisher,
			selectedSerialTypes,
			selectedOaModels,
			selectedDoaj,
			hasPublications: selectedPublications.length === 1 ? selectedPublications[0] : 'all',
			search,
			currentSort,
			currentPage: serials.page,
		}));
	}

	function onFilterChange() {
		serials.page = 1;
		syncUrl();
		serials.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(() => {
		serials.page = 1;
		syncUrl();
		serials.load();
		facets.load();
	});

	function setSort(column: 'title' | 'publisher' | 'publications') {
		currentSort = nextSort(currentSort, column, column === 'publications' ? 'desc' : 'asc');
		serials.page = 1;
		syncUrl();
		serials.load();
	}

	function formatIssns(j: Serial): string {
		return j.issns.join(' / ');
	}

	function serialTypeLabel(value: string | null): string {
		if (!value) return '';
		const opt = facets.options.serialTypes.find((o) => o.value === value);
		return opt ? opt.text : value;
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			if (restored.selectedPublisher) selectedPublisher = restored.selectedPublisher as string[];
			if (restored.selectedSerialTypes) selectedSerialTypes = restored.selectedSerialTypes as string[];
			if (restored.selectedOaModels) selectedOaModels = restored.selectedOaModels as string[];
			if (restored.selectedDoaj) selectedDoaj = restored.selectedDoaj as string[];
			if (restored.hasPublications != null && isAdmin()) {
				const value = restored.hasPublications as string;
				selectedPublications = value === 'all' ? [] : [value];
			}
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) serials.page = restored.currentPage as number;
		}
		await facets.load();
		serials.load();
	});
</script>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="search"
		placeholder="Rechercher par titre ou ISSN"
		bind:value={search}
		onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }}
		oninput={onSearchInput}
	/>
	{#if !publisherFixed}
		<EntityFilter
			label="Éditeur"
			endpoint="/api/serials/facets"
			kind="publisher"
			buildParams={buildFilterParams}
			selected={selectedPublisher}
			onchange={(ids) => { selectedPublisher = ids; onFilterChange(); }}
		/>
	{/if}
	<FacetDropdown
		label="Types"
		options={facets.options.serialTypes}
		bind:selected={selectedSerialTypes}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="DOAJ"
		options={facets.options.doaj}
		bind:selected={selectedDoaj}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="Modèle OA"
		options={facets.options.oaModels}
		bind:selected={selectedOaModels}
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
	<span class="count">{serials.total.toLocaleString('fr-FR')} publication{serials.total > 1 ? 's' : ''} en série</span>
</div>

<div class="table-scroll">
<table class="data-table journals-table">
	<thead>
		<tr>
			<th class="sortable" onclick={() => setSort('title')}>
				Titre <SortChevron direction={sortDirection(currentSort, 'title')} />
			</th>
			<th>ISSN</th>
			{#if !publisherFixed}
				<th class="sortable" onclick={() => setSort('publisher')}>
					Éditeur <SortChevron direction={sortDirection(currentSort, 'publisher')} />
				</th>
			{/if}
			<th>Type</th>
			<th class="num sortable" onclick={() => setSort('publications')}>
				Publis <SortChevron direction={sortDirection(currentSort, 'publications')} />
			</th>
			{#if actionCell}<th>{actionColumnHeader}</th>{/if}
		</tr>
	</thead>
	<tbody>
		{#each serials.items as j (j.id)}
			<tr>
				<td>
					<a href={resolve(`journals/${j.id}`)} class="entity-link">{j.title}</a>
					{#if j.is_in_doaj}
						{#if j.doaj_url}
							<a class="badge-doaj" href={j.doaj_url} target="_blank" rel="noopener" title="Fiche DOAJ (nouvel onglet)">DOAJ</a>
						{:else}
							<span class="badge-doaj" title="Indexée dans DOAJ">DOAJ</span>
						{/if}
					{/if}				</td>
				<td class="issn-cell">{formatIssns(j)}</td>
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
				{#if actionCell}<td class="actions row-actions">{@render actionCell(j)}</td>{/if}
			</tr>
		{/each}
		{#if serials.items.length === 0}
			<TableStatusRow loading={serials.loading} error={serials.error} colspan={(publisherFixed ? 4 : 5) + (actionCell ? 1 : 0)} emptyText="Aucune publication en série ne correspond aux filtres." />
		{/if}
	</tbody>
</table>
</div>

<Pagination
	page={serials.page}
	pages={serials.pages}
	onchange={(p) => {
		serials.page = p;
		syncUrl();
		serials.load();
	}}
/>

<style>
	/* Assez large pour que le texte indicatif du champ tienne en entier. */
	.toolbar input[type='search'] {
		width: 280px;
	}

	.journals-table { min-width: 660px; }
	.journals-table td.num { color: var(--muted); }
	.issn-cell {
		color: var(--muted);
		font-size: 0.85rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.muted { color: var(--muted); }


	.actions { white-space: nowrap; position: relative; }
</style>
