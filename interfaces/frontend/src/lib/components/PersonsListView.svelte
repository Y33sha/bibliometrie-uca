<script lang="ts">
	import { onMount } from 'svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { page } from '$app/state';
	import Pagination from '#lib/components/Pagination.svelte';
	import PersonsTable from '#lib/components/PersonsTable.svelte';
	import type { PersonRow } from '#lib/components/PersonsTable.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets, type FacetDef } from '#lib/composables/useFacets.svelte.js';
	import { useFilterPanel } from '#lib/composables/useFilterPanel.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import {
		activeCount,
		appendFilterParams,
		facetDefs,
		initialValues,
		restoreValues,
		urlFilterDefs,
		urlState,
		type PresenceCounts,
	} from '#lib/filterRegistry.js';
	import { PERSON_FILTER_GROUPS, PERSON_PRESENCE_FACETS, personFilters } from '#lib/personFilters.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import PersonCurationDrawer from '#lib/components/persons/PersonCurationDrawer.svelte';
	import { withBase } from '#lib/paths.js';
	import { paramsToQuery } from '#lib/utils.js';

	// Vue-liste des personnes réutilisable. Utilisée par :
	// - `/persons` (annuaire autonome avec sync URL)
	// - `/structures/[id]?tab=persons` (labo fixe via `labId`, sans sync URL ; la facette Laboratoires y présélectionne le labo)
	// La session admin y gagne les facettes Exclusion et À confirmer, les personnes sans contribution ni fiche RH, la colonne des publications du périmètre hors page de laboratoire, et une icône qui ouvre le volet de la personne.
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
		/** Contexte labo fixe : restreint l'annuaire aux personnes du laboratoire (période de présence ou contribution), et présélectionne le laboratoire dans la facette Laboratoires. */
		labId?: number;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Ouvre le volet de la personne dans la page hôte. Sans lui, la session admin ouvre le volet de la liste. */
		onopen?: (personId: number) => void;
		/** Personne ouverte par la page hôte, dont la ligne est mise en évidence. */
		activeId?: number | null;
	} = $props();

	// Volet de la liste, en session admin quand la page hôte n'en fournit pas : ouvert tant que `?person=<id>` figure dans l'URL.
	const ownDrawer = $derived(!onopen && isAdmin());
	const drawer = useDrawerParam('person', () => ownDrawer);
	// Incrémenté après chaque écriture du volet : la liste et ses facettes se rechargent.
	let listVersion = $state(0);

	// svelte-ignore state_referenced_locally
	const FILTERS = personFilters(labId);
	let values = $state(initialValues(FILTERS));
	const filterPanel = useFilterPanel();
	let search = $state('');
	let currentSort = $state('name_asc');

	// Filtres et terme de recherche.
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		// L'annuaire public écarte les personnes sans contribution ni fiche RH, conservées pour leurs décisions.
		if (!isAdmin()) params.set('active', 'yes');
		if (labId != null) params.set('lab_id', String(labId));
		appendFilterParams(FILTERS, values, params);
		const q = search.trim();
		if (q) params.set('search', q);
		return params;
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		return withBase(`/api/persons/export.csv?${paramsToQuery(params)}`);
	}

	const dir = usePaginatedFetch<PersonRow>({
		endpoint: '/api/persons',
		itemsKey: 'persons',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => `${apiKey}-${listVersion}`,
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			return params;
		}
	});

	// Décomptes des cases à cocher, et des éléments des filtres de présence (identifiants, éléments à confirmer), servis en deux options « avec » et « sans ».
	const presenceFacets = Object.fromEntries(
		PERSON_PRESENCE_FACETS.map((key) => [key, { type: 'boolean', apiKey: key, yesLabel: 'Avec', noLabel: 'Sans' } satisfies FacetDef]),
	);
	const facets = useFacets({
		endpoint: '/api/persons/facets',
		apiKey: () => `${apiKey}-${listVersion}-facets`,
		buildParams: buildFilterParams,
		facets: { ...facetDefs(FILTERS), ...presenceFacets },
	});

	const presenceCounts = $derived<PresenceCounts>(
		Object.fromEntries(
			PERSON_PRESENCE_FACETS.map((key) => {
				const options = facets.options[key] ?? [];
				return [key, { yes: options.find((o) => o.value === 'yes')?.count ?? 0, no: options.find((o) => o.value === 'no')?.count ?? 0 }];
			}),
		),
	);

	const url = useUrlFilters({
		basePath: () => basePath,
		debounceMs: 300,
		filters: {
			...urlFilterDefs(FILTERS),
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'name_asc' },
			currentPage: { type: 'page', urlKey: 'page' }
		}
	});

	function syncUrl() {
		if (!urlSync) return;
		url.syncUrl(() => ({
			...urlState(FILTERS, values),
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

	const onSearchInput = url.debouncedSearch(onFilterChange);

	onMount(async () => {
		if (urlSync) {
			const restored = url.restoreFromUrl(page.url.searchParams);
			restoreValues(FILTERS, restored, values);
			if (restored.search) search = restored.search as string;
			if (restored.currentSort) currentSort = restored.currentSort as string;
			if (restored.currentPage) dir.page = restored.currentPage as number;
		}
		await facets.load();
		dir.load();
	});
</script>

<ListToolbar bind:search placeholder="Rechercher par nom" onsearch={onSearchInput} list={dir} one="personne" many="personnes" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={filterPanel.open} active={activeCount(FILTERS, values)} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values options={facets.options} onchange={onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={filterPanel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={PERSON_FILTER_GROUPS} bind:values options={facets.options} {presenceCounts} loaded={facets.loaded} entityEndpoint="/api/persons/facets" buildParams={buildFilterParams} panel={filterPanel} onchange={onFilterChange} />
	{/snippet}
	<PersonsTable
		persons={dir.items}
		loading={dir.loading}
		error={dir.error}
		sort={currentSort}
		{onSortChange}
		perimeterCount={isAdmin() && labId == null}
		onopen={ownDrawer ? drawer.open : onopen}
		activeId={ownDrawer ? drawer.id : activeId}
	/>
	<Pagination
		page={dir.page}
		pages={dir.pages}
		onchange={(p) => {
			dir.goToPage(p);
			syncUrl();
		}}
	/>
</FilterLayout>

{#if drawer.id !== null}
	<PersonCurationDrawer
		personId={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={() => listVersion++}
		onopenPerson={drawer.open}
	/>
{/if}
