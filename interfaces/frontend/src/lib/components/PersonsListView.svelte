<script lang="ts">
	import { onMount } from 'svelte';
	import { autofocus } from '#lib/actions/focus.js';
	import { page } from '$app/state';
	import FacetDropdown, { type FacetOption } from '#lib/components/FacetDropdown.svelte';
	import PresenceFilterToggle from '#lib/components/PresenceFilterToggle.svelte';
	import { IDENTIFIER_ITEMS, PENDING_ITEMS } from '#lib/filterItems.js';
	import { personExclusionLabels } from '#lib/labels.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import PersonsTable from '#lib/components/PersonsTable.svelte';
	import type { PersonRow } from '#lib/components/PersonsTable.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';

	type IdState = 'all' | 'yes' | 'no';

	// Vue-liste des personnes réutilisable. Utilisée par :
	// - `/persons` (annuaire autonome avec sync URL ; en session admin, une icône ouvre le volet de la personne)
	// - `/structures/[id]?tab=persons` (labo fixe via `labId`, sans sync URL)
	// La session admin y gagne les facettes Exclusion, Activité et À confirmer, et la colonne des publications du périmètre.
	let {
		apiKey = 'persons-dir',
		labId,
		urlSync = true,
		basePath = '/persons',
		perPage = 50,
		onopen,
		activeId = null,
	}: {
		apiKey?: string;
		/** Contexte labo fixe : scope l'annuaire aux personnes du laboratoire. */
		labId?: number;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Ouvre le volet de la personne dans la page hôte. */
		onopen?: (personId: number) => void;
		/** Personne ouverte par la page hôte, dont la ligne est mise en évidence. */
		activeId?: number | null;
	} = $props();

	// `none` désigne les personnes retenues, comme dans le paramètre `exclusion` de l'API.
	const exclusionOptions: FacetOption[] = [
		{ value: 'none', text: 'Retenue' },
		...Object.entries(personExclusionLabels).map(([value, text]) => ({ value, text })),
	];
	const activityOptions: FacetOption[] = [
		{ value: 'yes', text: 'Avec contribution ou fiche RH' },
		{ value: 'no', text: 'Sans contribution ni fiche RH' },
	];

	let search = $state('');
	let selectedDepts: string[] = $state([]);
	let selectedRoles: string[] = $state([]);
	let idStates = $state<Record<string, IdState>>({});
	let selectedRh: string[] = $state(['yes']);
	let currentSort = $state('name_asc');
	// Restrictions de l'annuaire : personnes retenues, actives. Seule la session admin change ces réglages.
	let selectedExclusions: string[] = $state(['none']);
	let selectedActivity: string[] = $state(['yes']);
	let pendingStates = $state<Record<string, IdState>>({});

	const idQueryKey: Record<string, string> = {
		orcid: 'has_orcid',
		idhal: 'has_idhal',
		idref: 'has_idref'
	};
	const pendingQueryKey: Record<string, string> = {
		pending_forms: 'has_pending_forms',
		pending_identifiers: 'has_pending_identifiers',
	};

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedExclusions.length) params.set('exclusion', selectedExclusions.join(','));
		if (selectedActivity.length === 1) params.set('active', selectedActivity[0]);
		if (selectedDepts.length) params.set('department', selectedDepts.join(','));
		if (selectedRoles.length) params.set('role', selectedRoles.join(','));
		for (const [key, qk] of Object.entries(idQueryKey)) {
			const v = idStates[key];
			if (v === 'yes' || v === 'no') params.set(qk, v);
		}
		for (const [key, qk] of Object.entries(pendingQueryKey)) {
			const v = pendingStates[key];
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
		// Inclut le terme de recherche pour que les comptes de facettes suivent le champ de recherche (comme l'annuaire).
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
			rh: { type: 'boolean', apiKey: 'rh', yesLabel: 'Oui', noLabel: 'Non' },
			pending_forms: { type: 'boolean', apiKey: 'pending_forms', yesLabel: 'Avec', noLabel: 'Sans' },
			pending_identifiers: { type: 'boolean', apiKey: 'pending_identifiers', yesLabel: 'Avec', noLabel: 'Sans' },
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
	const pendingCounts = $derived({
		pending_forms: yesNoFromFacet('pending_forms'),
		pending_identifiers: yesNoFromFacet('pending_identifiers'),
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		debounceMs: 300,
		filters: {
			selectedDepts: { type: 'string_array', urlKey: 'department' },
			selectedRoles: { type: 'string_array', urlKey: 'role' },
			idStates: { type: 'source_states', urlKey: 'id_filter' },
			hasRh: { type: 'single', urlKey: 'has_rh', defaultValue: 'yes' },
			exclusion: { type: 'single', urlKey: 'exclusion', defaultValue: 'none' },
			activity: { type: 'single', urlKey: 'active', defaultValue: 'yes' },
			pendingStates: { type: 'source_states', urlKey: 'pending_filter' },
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
			exclusion: selectedExclusions.length ? selectedExclusions.join(',') : 'all',
			activity: selectedActivity.length === 1 ? selectedActivity[0] : 'all',
			pendingStates,
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
			const restored = url.restoreFromUrl(page.url.searchParams);
			if (restored.selectedDepts) selectedDepts = restored.selectedDepts as string[];
			if (restored.selectedRoles) selectedRoles = restored.selectedRoles as string[];
			if (restored.idStates) idStates = restored.idStates as Record<string, IdState>;
			if (restored.hasRh != null) {
				const rh = restored.hasRh as string;
				selectedRh = rh === 'all' ? [] : [rh];
			}
			if (isAdmin()) {
				if (restored.exclusion != null) {
					const value = restored.exclusion as string;
					selectedExclusions = value === 'all' ? [] : value.split(',');
				}
				if (restored.activity != null) {
					const value = restored.activity as string;
					selectedActivity = value === 'all' ? [] : [value];
				}
				if (restored.pendingStates) pendingStates = restored.pendingStates as Record<string, IdState>;
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
	{#if isAdmin()}
		<PresenceFilterToggle
			label="À confirmer"
			items={PENDING_ITEMS}
			bind:states={pendingStates}
			counts={pendingCounts}
			onchange={onFilterChange}
		/>
		<FacetDropdown label="Activité" options={activityOptions} bind:selected={selectedActivity} onchange={onFilterChange} />
		<FacetDropdown label="Exclusion" options={exclusionOptions} allLabel="Toutes" bind:selected={selectedExclusions} onchange={onFilterChange} />
	{/if}
	<span class="count">{dir.total} personne{dir.total > 1 ? 's' : ''}</span>
</div>

<PersonsTable
	persons={dir.items}
	loading={dir.loading}
	error={dir.error}
	sort={currentSort}
	{onSortChange}
	perimeterCount={isAdmin()}
	{onopen}
	{activeId}
/>

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
