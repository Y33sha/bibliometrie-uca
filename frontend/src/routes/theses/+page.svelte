<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { sanitizeTitle } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	interface Thesis {
		id: number;
		title: string;
		pub_year: number | null;
		doi: string | null;
		doc_type: string | null;
		labs: string | null;
		theses_id: string | null;
	}

	let search = $state('');
	let currentSort = $state('year_desc');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let selectedStatus: string[] = $state([]);

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		if (selectedLabs.length) params.set('lab_id', selectedLabs.join(','));
		if (selectedStatus.length) {
			params.set('doc_type', selectedStatus.join(','));
		} else {
			params.set('doc_type', 'thesis,ongoing_thesis');
		}
		const q = search.trim();
		if (q) params.set('search', q);
		params.set('sort', currentSort);
		return params;
	}

	const pubs = usePaginatedFetch<Thesis>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		perPage: 100,
		apiKey: 'theses-list',
		buildParams: buildFilterParams,
	});

	const facets = useFacets({
		endpoint: '/api/publications/facets',
		apiKey: 'theses-facets',
		buildParams: buildFilterParams,
		facets: {
			years: { type: 'simple', apiKey: 'years' },
			labs: { type: 'labeled', apiKey: 'labs' },
			status: {
				type: 'label_map', apiKey: 'doc_types',
				labels: { thesis: 'Soutenues', ongoing_thesis: 'En cours' },
			},
		},
		afterLoad(_data, options) {
			options.labs = [
				{ value: 'none', text: '— Aucun labo —', count: (_data.no_lab_count as number) ?? 0 },
				...options.labs,
			];
			options.status = options.status.filter(
				(f) => f.value === 'thesis' || f.value === 'ongoing_thesis'
			);
		},
	});

	const url = useUrlFilters({
		basePath: '/theses',
		filters: {
			selectedYears:  { type: 'string_array', urlKey: 'year' },
			selectedLabs:   { type: 'string_array', urlKey: 'lab_id' },
			selectedStatus: { type: 'string_array', urlKey: 'status' },
			search:         { type: 'single',       urlKey: 'search' },
			currentSort:    { type: 'single',       urlKey: 'sort', defaultValue: 'year_desc' },
			currentPage:    { type: 'page',          urlKey: 'page' },
		},
	});

	function syncUrl() {
		url.syncUrl(() => ({
			selectedYears, selectedLabs, selectedStatus, search, currentSort,
			currentPage: pubs.page,
		}));
	}

	function onFilterChange() {
		pubs.page = 1;
		syncUrl();
		pubs.load();
		facets.load();
	}

	function onLabChange(newSelection: string[]) {
		const hadNone = selectedLabs.includes('none');
		const hasNone = newSelection.includes('none');
		if (hasNone && !hadNone) selectedLabs = ['none'];
		else if (hasNone && newSelection.length > 1) selectedLabs = newSelection.filter((v: string) => v !== 'none');
		else selectedLabs = newSelection;
		onFilterChange();
	}

	const onSearchInput = url.debouncedSearch(() => {
		pubs.page = 1;
		syncUrl();
		pubs.load();
	});

	function toggleSortYear() {
		currentSort = currentSort === 'year_desc' ? 'year_asc' : 'year_desc';
		onFilterChange();
	}

	const yearSortArrow = $derived(currentSort === 'year_asc' ? '↑' : '↓');
	const yearSortActive = $derived(currentSort === 'year_desc' || currentSort === 'year_asc');

	onMount(async () => {
		const restored = url.restoreFromUrl($page.url.searchParams);
		if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
		if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
		if (restored.selectedStatus) selectedStatus = restored.selectedStatus as string[];
		if (restored.search) search = restored.search as string;
		if (restored.currentSort) currentSort = restored.currentSort as string;
		if (restored.currentPage) pubs.page = restored.currentPage as number;

		await facets.load();
		pubs.load();
	});
</script>

<svelte:head><title>Thèses — Bibliométrie UCA</title></svelte:head>

<div class="page-header">
	<h2>Thèses</h2>
	<span class="result-count">{pubs.total} résultats</span>
</div>

<div class="toolbar">
	<input type="search" placeholder="Rechercher par titre, auteur..."
		bind:value={search}
		oninput={onSearchInput}
		onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter') { e.preventDefault(); onFilterChange(); }}}
	/>

	<div class="facets">
		<FacetDropdown label="Année" options={facets.options.years} bind:selected={selectedYears}
			onchange={() => onFilterChange()} />
		<FacetDropdown label="Laboratoire" options={facets.options.labs} bind:selected={selectedLabs}
			onchange={(v: string[]) => onLabChange(v)} />
		<FacetDropdown label="Statut" options={facets.options.status} bind:selected={selectedStatus}
			onchange={() => onFilterChange()} />
	</div>
</div>

<table class="data-table">
	<thead>
		<tr>
			<th class="col-year sortable" class:active={yearSortActive}
				onclick={toggleSortYear}>Année {yearSortArrow}</th>
			<th class="col-title">Titre</th>
			<th class="col-status">Statut</th>
			<th class="col-labs">Laboratoire(s)</th>
			<th class="col-link">Lien</th>
		</tr>
	</thead>
	<tbody>
		{#each pubs.items as pub (pub.id)}
			<tr>
				<td class="col-year">{pub.pub_year || ''}</td>
				<td class="col-title">
					<a href="{base}/publications/{pub.id}">{@html sanitizeTitle(pub.title)}</a>
				</td>
				<td class="col-status">
					<span class="status-badge" class:soutenue={pub.doc_type === 'thesis'} class:en-cours={pub.doc_type === 'ongoing_thesis'}>
						{pub.doc_type === 'thesis' ? 'Soutenue' : pub.doc_type === 'ongoing_thesis' ? 'En cours' : ''}
					</span>
				</td>
				<td class="col-labs">{pub.labs || ''}</td>
				<td class="col-link">
					{#if pub.theses_id}
						<a href="https://theses.fr/{pub.theses_id}" target="_blank" rel="noopener" class="ext-link">theses.fr</a>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<Pagination page={pubs.page} pages={pubs.pages}
	onchange={(p: number) => { pubs.page = p; syncUrl(); pubs.load(); }} />

<style>
	.page-header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
	.page-header h2 { margin: 0; font-size: 1.2rem; }
	.result-count { font-size: 0.85rem; color: var(--muted); }

	.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 12px; position: sticky; top: 46px; background: var(--bg); padding: 6px 0; }
	.toolbar input[type="search"] { width: 280px; padding: 5px 10px; font-size: 0.9rem; font-family: inherit; border: 1px solid var(--border); border-radius: 4px; }
	.facets { display: flex; gap: 6px; flex-wrap: wrap; }

	.data-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	.data-table th { text-align: left; padding: 6px 8px; border-bottom: 2px solid var(--border); font-size: 0.8rem; color: var(--muted); text-transform: uppercase; }
	.data-table td { padding: 5px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
	.data-table tbody tr:hover { background: var(--hover); }

	.col-year { width: 60px; text-align: center; }
	.col-title { min-width: 300px; }
	.col-title a { color: inherit; text-decoration: none; }
	.col-title a:hover { color: var(--accent); }
	.col-status { width: 90px; text-align: center; }
	.col-labs { width: 180px; font-size: 0.85rem; color: var(--muted); }
	.col-link { width: 70px; text-align: center; }
	.ext-link { font-size: 0.8rem; color: var(--accent); text-decoration: none; }
	.ext-link:hover { text-decoration: underline; }

	.sortable { cursor: pointer; user-select: none; }
	.sortable.active { color: var(--accent); }

	.status-badge { font-size: 0.75rem; padding: 2px 6px; border-radius: 8px; }
	.status-badge.soutenue { background: #e8f5e9; color: #2e7d32; }
	.status-badge.en-cours { background: #fff3e0; color: #e65100; }
</style>
