<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import PresenceFilterToggle from '$lib/components/PresenceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import ThesesTable from '$lib/components/ThesesTable.svelte';
	import type { ThesisRow } from '$lib/components/ThesesTable.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	// Vue-liste des thèses réutilisable. Utilisée par :
	// - `/theses` (mode autonome avec sync URL)
	// - `/laboratories/[id]?tab=theses` (labo fixe via `labId`, sans sync URL)
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

	const hasFixedLab = $derived(labId != null);

	let search = $state('');
	let currentSort = $state('soutenance_desc');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let selectedStatus: string[] = $state([]);
	let selectedAccess: string[] = $state([]);
	let sourceStates: Record<string, 'all' | 'yes' | 'no'> = $state({});

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (hasFixedLab) params.set('lab_id', String(labId));
		else if (selectedLabs.length) params.set('lab_id', selectedLabs.join(','));
		if (selectedStatus.length) params.set('doc_type', selectedStatus.join(','));
		else params.set('doc_type', 'thesis,ongoing_thesis');
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		const q = search.trim();
		if (q) params.set('search', q);
		if (selectedAccess.length) params.set('access', selectedAccess.join(','));
		const sf = Object.entries(sourceStates)
			.filter(([, v]) => v === 'yes' || v === 'no')
			.map(([k, v]) => `${k}_${v}`)
			.join(',');
		if (sf) params.set('source_filter', sf);
		params.set('sort', currentSort);
		return params;
	}

	const pubs = usePaginatedFetch<ThesisRow>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		perPage,
		apiKey,
		buildParams: buildFilterParams
	});

	const facets = useFacets({
		endpoint: '/api/publications/facets',
		apiKey: `${apiKey}-facets`,
		buildParams: buildFilterParams,
		sourceCountsKey: 'source_counts',
		facets: {
			years: { type: 'simple', apiKey: 'years' },
			labs: { type: 'labeled', apiKey: 'labs' },
			access: { type: 'passthrough', apiKey: 'access' },
			status: {
				type: 'label_map',
				apiKey: 'doc_types',
				labels: { thesis: 'Soutenues', ongoing_thesis: 'En cours' }
			}
		},
		afterLoad(_data, options) {
			options.labs = [
				{ value: 'none', text: '— Aucun labo —', count: (_data.no_lab_count as number) ?? 0 },
				...options.labs
			];
			options.status = options.status.filter(
				(f) => f.value === 'thesis' || f.value === 'ongoing_thesis'
			);
		}
	});

	const url = useUrlFilters({
		basePath,
		filters: {
			selectedYears: { type: 'string_array', urlKey: 'year' },
			selectedLabs: { type: 'string_array', urlKey: 'lab_id' },
			selectedStatus: { type: 'string_array', urlKey: 'status' },
			selectedAccess: { type: 'string_array', urlKey: 'access' },
			sourceStates: { type: 'source_states', urlKey: 'source_filter' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'soutenance_desc' },
			currentPage: { type: 'page', urlKey: 'page' }
		}
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedYears,
			selectedLabs,
			selectedStatus,
			selectedAccess,
			sourceStates,
			search,
			currentSort,
			currentPage: pubs.page
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
		else if (hasNone && newSelection.length > 1)
			selectedLabs = newSelection.filter((v: string) => v !== 'none');
		else selectedLabs = newSelection;
		onFilterChange();
	}

	const onSearchInput = url.debouncedSearch(() => {
		pubs.page = 1;
		syncUrl();
		pubs.load();
	});

	function toggleSort(asc: string, desc: string) {
		currentSort = currentSort === desc ? asc : desc;
		onFilterChange();
	}

	function exportCsvUrl(): string {
		return `${base}/api/publications/export-theses.csv?${buildFilterParams()}`;
	}

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
			if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
			if (restored.selectedStatus) selectedStatus = restored.selectedStatus as string[];
			if (restored.selectedAccess) selectedAccess = restored.selectedAccess as string[];
			if (restored.sourceStates)
				sourceStates = restored.sourceStates as Record<string, 'all' | 'yes' | 'no'>;
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) pubs.page = restored.currentPage as number;
		}
		await facets.load();
		pubs.load();
	});
</script>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="text"
		placeholder="Rechercher par titre..."
		bind:value={search}
		oninput={onSearchInput}
		onkeydown={(e: KeyboardEvent) => {
			if (e.key === 'Enter') {
				e.preventDefault();
				onFilterChange();
			}
		}}
	/>
	<FacetDropdown label="Année" options={facets.options.years} bind:selected={selectedYears} onchange={() => onFilterChange()} />
	{#if !hasFixedLab}
		<FacetDropdown label="Laboratoire" options={facets.options.labs} bind:selected={selectedLabs} onchange={(v: string[]) => onLabChange(v)} />
	{/if}
	<FacetDropdown label="Statut" options={facets.options.status} bind:selected={selectedStatus} onchange={() => onFilterChange()} />
	<FacetDropdown label="Accès" options={facets.options.access} bind:selected={selectedAccess} onchange={() => onFilterChange()} />
	<PresenceFilterToggle
		label="Sources"
		items={[
			{ key: 'hal', label: 'HAL' },
			{ key: 'oa', label: 'OpenAlex' },
			{ key: 'scanr', label: 'ScanR' },
			{ key: 'theses', label: 'theses.fr' }
		]}
		bind:states={sourceStates}
		counts={facets.sourceCounts}
		onchange={() => onFilterChange()}
	/>
	<span class="count">{pubs.total} thèse{pubs.total > 1 ? 's' : ''}</span>
	<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
</div>

<ThesesTable items={pubs.items} loading={pubs.loading} sort={currentSort} onToggleSort={toggleSort} showLabsColumn={!hasFixedLab} />
<Pagination
	page={pubs.page}
	pages={pubs.pages}
	onchange={(p: number) => {
		pubs.page = p;
		syncUrl();
		pubs.load();
	}}
/>

<style>
	.toolbar input[type='text'] {
		width: 280px;
	}
</style>
