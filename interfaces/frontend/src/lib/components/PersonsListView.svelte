<script lang="ts">
	import { onMount } from 'svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import PersonsTable from '#lib/components/PersonsTable.svelte';
	import type { PersonRow } from '#lib/components/PersonsTable.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { useFacets, type FacetDef } from '#lib/composables/useFacets.svelte.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { facetDefs, type PresenceCounts } from '#lib/filterRegistry.js';
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

	// Décomptes des cases à cocher, et des éléments des filtres de présence (identifiants, éléments à confirmer), servis en deux options « avec » et « sans ».
	const presenceFacets = Object.fromEntries(
		PERSON_PRESENCE_FACETS.map((key) => [key, { type: 'boolean', apiKey: key, yesLabel: 'Avec', noLabel: 'Sans' } satisfies FacetDef]),
	);

	const list = useFilteredList<PersonRow, ReturnType<typeof useFacets>>({
		filters: FILTERS,
		baseParams() {
			const params = new URLSearchParams();
			// L'annuaire public écarte les personnes sans contribution ni fiche RH, conservées pour leurs décisions.
			if (!isAdmin()) params.set('active', 'yes');
			if (labId != null) params.set('lab_id', String(labId));
			return params;
		},
		endpoint: '/api/persons',
		itemsKey: 'persons',
		// svelte-ignore state_referenced_locally
		perPage,
		apiKey: () => `${apiKey}-${listVersion}`,
		defaultSort: 'name_asc',
		urlSync: () => urlSync,
		basePath: () => basePath,
		debounceMs: 300,
		facets: (buildParams) =>
			useFacets({
				endpoint: '/api/persons/facets',
				apiKey: () => `${apiKey}-${listVersion}-facets`,
				buildParams,
				facets: { ...facetDefs(FILTERS), ...presenceFacets },
			}),
	});

	const presenceCounts = $derived<PresenceCounts>(
		Object.fromEntries(
			PERSON_PRESENCE_FACETS.map((key) => {
				const options = list.facets.options[key] ?? [];
				return [key, { yes: options.find((o) => o.value === 'yes')?.count ?? 0, no: options.find((o) => o.value === 'no')?.count ?? 0 }];
			}),
		),
	);

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', list.sort);
		return withBase(`/api/persons/export.csv?${paramsToQuery(params)}`);
	}

	onMount(list.restore);
</script>

<ListToolbar bind:search={list.search} placeholder="Rechercher par nom" onsearch={list.onSearchInput} list={list.listing} one="personne" many="personnes" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={PERSON_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} {presenceCounts} loaded={list.facets.loaded} entityEndpoint="/api/persons/facets" buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}
	<PersonsTable
		persons={list.listing.items}
		loading={list.listing.loading}
		error={list.listing.error}
		sort={list.sort}
		onSortChange={list.setSort}
		perimeterCount={isAdmin() && labId == null}
		onopen={ownDrawer ? drawer.open : onopen}
		activeId={ownDrawer ? drawer.id : activeId}
	/>
	<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>

{#if drawer.id !== null}
	<PersonCurationDrawer
		personId={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={() => listVersion++}
		onopenPerson={drawer.open}
	/>
{/if}
