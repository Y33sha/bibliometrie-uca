<script lang="ts">
	import { onMount } from 'svelte';
	import { autofocus } from '$lib/actions/focus';
	import { page } from '$app/stores';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import PresenceFilterToggle from '$lib/components/PresenceFilterToggle.svelte';
	import { IDENTIFIER_ITEMS } from '$lib/filterItems';
	import Pagination from '$lib/components/Pagination.svelte';
	import PersonsTable from '$lib/components/PersonsTable.svelte';
	import type { PersonRow } from '$lib/components/PersonsTable.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	type IdState = 'all' | 'yes' | 'no';

	// Vue-liste des personnes réutilisable. Utilisée par :
	// - `/persons` (annuaire autonome avec sync URL)
	// - `/laboratories/[id]?tab=persons` (labo fixe via `labId`, sans sync URL)
	let {
		apiKey = 'persons-dir',
		labId,
		urlSync = true,
		basePath = '/persons',
		perPage = 50
	}: {
		apiKey?: string;
		/** Contexte labo fixe : scope l'annuaire aux personnes du laboratoire. */
		labId?: number;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
	} = $props();

	let search = $state('');
	let selectedDepts: string[] = $state([]);
	let selectedRoles: string[] = $state([]);
	let idStates = $state<Record<string, IdState>>({});
	let selectedRh: string[] = $state(['yes']);
	let currentSort = $state('name_asc');

	const idQueryKey: Record<string, string> = {
		orcid: 'has_orcid',
		idhal: 'has_idhal',
		idref: 'has_idref'
	};

	function buildFilterParams(): URLSearchParams {
		// L'annuaire ne montre pas les personnes que la curation a écartées.
		const params = new URLSearchParams({ rejected: 'false' });
		if (selectedDepts.length) params.set('department', selectedDepts.join(','));
		if (selectedRoles.length) params.set('role', selectedRoles.join(','));
		for (const [key, qk] of Object.entries(idQueryKey)) {
			const v = idStates[key];
			if (v === 'yes' || v === 'no') params.set(qk, v);
		}
		if (selectedRh.length === 1) params.set('has_rh', selectedRh[0]);
		if (labId != null) params.set('lab_id', String(labId));
		return params;
	}

	const dir = usePaginatedFetch<PersonRow>({
		endpoint: '/api/persons',
		itemsKey: 'persons',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => apiKey,
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set('search', q);
			params.set('sort', currentSort);
			return params;
		}
	});

	const facets = useFacets({
		endpoint: '/api/persons/facets',
		apiKey: () => `${apiKey}-facets`,
		// Inclut le terme de recherche pour que les comptes de facettes suivent le
		// champ de recherche (comme l'annuaire).
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
		facets: {
			depts: { type: 'simple', apiKey: 'departments' },
			roles: { type: 'simple', apiKey: 'roles' },
			orcid: { type: 'boolean', apiKey: 'orcid', yesLabel: 'Avec', noLabel: 'Sans' },
			idhal: { type: 'boolean', apiKey: 'idhal', yesLabel: 'Avec', noLabel: 'Sans' },
			idref: { type: 'boolean', apiKey: 'idref', yesLabel: 'Avec', noLabel: 'Sans' },
			rh: { type: 'boolean', apiKey: 'rh', yesLabel: 'Oui', noLabel: 'Non' }
		}
	});

	function yesNoFromFacet(key: string): { yes: number; no: number } {
		const opts = facets.options[key as keyof typeof facets.options] || [];
		return {
			yes: opts.find((o) => o.value === 'yes')?.count ?? 0,
			no: opts.find((o) => o.value === 'no')?.count ?? 0
		};
	}

	const idCounts = $derived({
		orcid: yesNoFromFacet('orcid'),
		idhal: yesNoFromFacet('idhal'),
		idref: yesNoFromFacet('idref')
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		debounceMs: 300,
		filters: {
			selectedDepts: { type: 'string_array', urlKey: 'department' },
			selectedRoles: { type: 'string_array', urlKey: 'role' },
			idStates: { type: 'source_states', urlKey: 'id_filter' },
			hasRh: { type: 'single', urlKey: 'has_rh', defaultValue: 'yes' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'name_asc' },
			currentPage: { type: 'page', urlKey: 'page' }
		}
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			selectedDepts,
			selectedRoles,
			idStates,
			hasRh: selectedRh.length === 1 ? selectedRh[0] : 'all',
			search,
			currentSort,
			currentPage: dir.page
		}));
	}

	function onFilterChange() {
		dir.page = 1;
		syncUrl();
		dir.load();
		facets.load();
	}

	function onSortChange(newSort: string) {
		currentSort = newSort;
		dir.page = 1;
		syncUrl();
		dir.load();
	}

	const onSearchInput = url.debouncedSearch(() => {
		dir.page = 1;
		syncUrl();
		dir.load();
		facets.load();
	});

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl($page.url.searchParams);
			if (restored.selectedDepts) selectedDepts = restored.selectedDepts as string[];
			if (restored.selectedRoles) selectedRoles = restored.selectedRoles as string[];
			if (restored.idStates) idStates = restored.idStates as Record<string, IdState>;
			if (restored.hasRh != null) {
				const rh = restored.hasRh as string;
				selectedRh = rh === 'all' ? [] : [rh];
			}
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) dir.page = restored.currentPage as number;
		}
		await facets.load();
		dir.load();
	});
</script>

<div class="toolbar toolbar-card toolbar-sticky">
	<input type="search" placeholder="Rechercher par nom..." bind:value={search} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
	<PresenceFilterToggle
		label="Identifiants"
		items={IDENTIFIER_ITEMS}
		bind:states={idStates}
		counts={idCounts}
		onchange={onFilterChange}
	/>
	<FacetDropdown label="Fonction" options={facets.options.roles} searchable bind:selected={selectedRoles} onchange={onFilterChange} />
	<FacetDropdown label="Département" options={facets.options.depts} searchable bind:selected={selectedDepts} onchange={onFilterChange} />
	<FacetDropdown label="Base RH" options={facets.options.rh} bind:selected={selectedRh} onchange={onFilterChange} />
	<span class="count">{dir.total} personne{dir.total > 1 ? 's' : ''}</span>
</div>

<PersonsTable persons={dir.items} loading={dir.loading} sort={currentSort} {onSortChange} />

<Pagination
	page={dir.page}
	pages={dir.pages}
	onchange={(p) => {
		dir.goToPage(p);
		syncUrl();
	}}
/>

<style>
	.toolbar input[type='search'] {
		width: 240px;
	}
</style>
