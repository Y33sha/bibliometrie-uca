<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { columnLabels } from '#lib/labels.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { structures as structuresApi, errorMessage } from '#lib/api/index.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { facetDefs } from '#lib/filterRegistry.js';
	import { STRUCTURE_FILTER_GROUPS, structureFilters } from '#lib/structureFilters.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import { withBase } from '#lib/paths.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import { halCollectionUrl, paramsToQuery, rorShortId, rorFullUrl } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import IconButton from '#lib/components/IconButton.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import StructureDrawer from '#lib/components/structures/StructureDrawer.svelte';
	import StructureFormModal from '#lib/components/structures/StructureFormModal.svelte';
	import StructureTypeTag from '#lib/components/structures/StructureTypeTag.svelte';
	import { ROR_FORMAT_ERROR, buildApiIds, normalizeRorId } from '#lib/components/structures/types.js';

	import type { components } from '#lib/api/schema.js';
	import type { PageData } from './$types';
	type Structure = components['schemas']['StructureListItem'];

	let { data }: { data: PageData } = $props();

	// svelte-ignore state_referenced_locally
	const FILTERS = structureFilters(data.labDefaults);

	const list = useFilteredList<Structure, ReturnType<typeof useFacets>>({
		filters: FILTERS,
		endpoint: '/api/structures',
		itemsKey: 'structures',
		perPage: 100,
		apiKey: () => 'structures-list',
		defaultSort: 'acronym_asc',
		urlSync: () => true,
		basePath: () => '/structures',
		facets: (buildParams) =>
			useFacets({
				endpoint: '/api/structures/facets',
				apiKey: 'structures-facets',
				buildParams,
				facets: facetDefs(FILTERS),
			}),
	});

	function exportCsvUrl(): string {
		const params = list.filterParams();
		params.set('sort', list.sort);
		return withBase(`/api/structures/export.csv?${paramsToQuery(params)}`);
	}

	// Volet d'édition d'une structure, en session admin : ouvert tant que `?structure=<id>` figure dans l'URL.
	const drawer = useDrawerParam('structure', isAdmin);

	// Le type s'affiche dès que la liste mêle plusieurs types.
	const showTypeColumn = $derived(list.values.checkbox.types.length !== 1);

	function toggleSort(column: 'acronym' | 'name' | 'tutelles') {
		list.setSort(nextSort(list.sort, column, 'asc'));
	}

	// Création d'une structure (session admin)
	let createModalOpen = $state(false);
	let mCode = $state('');
	let mName = $state('');
	let mAcronym = $state('');
	let mType = $state('labo');
	let mRor = $state('');
	let mHal = $state('');
	let mApiIds: Record<string, string> = $state({});

	function openCreateModal() {
		mCode = '';
		mName = '';
		mAcronym = '';
		mType = 'labo';
		mRor = '';
		mHal = '';
		mApiIds = {};
		createModalOpen = true;
	}

	async function submitCreate() {
		const ror = normalizeRorId(mRor);
		if (ror === null) {
			toast(ROR_FORMAT_ERROR, 'error');
			return;
		}
		mRor = ror;
		const data: Record<string, any> = {
			code: mCode.trim(),
			name: mName.trim(),
			acronym: mAcronym.trim() || null,
			type: mType,
			ror_id: mRor.trim() || null,
			hal_collection: mHal.trim() || null,
			api_ids: buildApiIds(mApiIds),
		};
		if (!data.code || !data.name) {
			toast('Code et nom requis', 'error');
			return;
		}
		try {
			const created = (await structuresApi.create(data)) as { id: number };
			createModalOpen = false;
			list.listing.load();
			drawer.open(created.id);
		} catch (e) {
			toast('Erreur: ' + errorMessage(e), 'error');
		}
	}

	onMount(list.restore);
</script>

<PageHeader title="Labos" hidden />

<ListToolbar bind:search={list.search} placeholder="Rechercher par nom ou acronyme" onsearch={list.onSearchInput} list={list.listing} one="structure" many="structures" exportUrl={exportCsvUrl()} countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet actions()}
		{#if isAdmin()}
			<button class="btn btn-primary btn-sm" onclick={openCreateModal}>+ Nouvelle</button>
		{/if}
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={FILTERS} groups={STRUCTURE_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={{}} loaded={list.facets.loaded} entityEndpoint="/api/structures/facets" buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}

<TableScroll>
<table class="data-table">
	<thead>
		<tr>
			{#if isAdmin()}<th class="row-actions"></th>{/if}
			{#if showTypeColumn}<th>{columnLabels.type}</th>{/if}
			<th class="sortable" class:active={sortDirection(list.sort,'acronym') !== null} onclick={() => toggleSort('acronym')}>
				Acronyme
				<SortChevron direction={sortDirection(list.sort,'acronym')} />
			</th>
			<th class="sortable" class:active={sortDirection(list.sort,'name') !== null} onclick={() => toggleSort('name')}>
				Nom
				<SortChevron direction={sortDirection(list.sort,'name')} />
			</th>
			<th class="sortable tutelles-col" class:active={sortDirection(list.sort,'tutelles') !== null} onclick={() => toggleSort('tutelles')}>
				Tutelles
				<SortChevron direction={sortDirection(list.sort,'tutelles')} />
			</th>
			<th>ROR</th>
			<th>Collection HAL</th>
		</tr>
	</thead>
	<tbody>
		{#if list.listing.items.length === 0}
			<TableStatusRow loading={list.listing.loading} error={list.listing.error} colspan={5 + (showTypeColumn ? 1 : 0) + (isAdmin() ? 1 : 0)} emptyText="Aucune structure ne correspond aux filtres." />
		{/if}
		{#each list.listing.items as s (s.id)}
			<tr class:active-row={s.id === drawer.id}>
				{#if isAdmin()}
					<td class="row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(s.id)} />
					</td>
				{/if}
				{#if showTypeColumn}
					<td><StructureTypeTag type={s.type} /></td>
				{/if}
				<td class="acronym-cell">
					{#if s.acronym}<a href={resolve(`structures/${s.id}`)} class="entity-link">{s.acronym}</a>{/if}
				</td>
				<td>
					<a href={resolve(`structures/${s.id}`)} class="entity-link">{s.name}</a>
				</td>
				<td class="tutelles-col">
					<div class="tutelles">
						{#each s.tutelles || [] as t (t.id)}
							<span class="tag">{structureLabel(t)}</span>
						{/each}
					</div>
				</td>
				<td>
					{#if s.ror_id}
						<a href={rorFullUrl(s.ror_id)} target="_blank" rel="noopener" class="tag id-badge">
							{rorShortId(s.ror_id)}
						</a>
					{/if}
				</td>
				<td>
					{#if s.hal_collection}
						<a href={halCollectionUrl(s.hal_collection)} target="_blank" rel="noopener" class="tag id-badge">
							{s.hal_collection}
						</a>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>
</TableScroll>

<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>

{#if drawer.id !== null}
	<StructureDrawer id={drawer.id} onclose={() => drawer.open(null)} onchange={() => list.listing.load()} onopenStructure={drawer.open} />
{/if}

{#if createModalOpen}
	<StructureFormModal
		editMode={false}
		bind:code={mCode}
		bind:name={mName}
		bind:acronym={mAcronym}
		bind:type={mType}
		bind:ror={mRor}
		bind:hal={mHal}
		bind:apiIds={mApiIds}
		onclose={() => (createModalOpen = false)}
		onsubmit={submitCreate}
	/>
{/if}

<style>
	td {
		vertical-align: middle;
	}
	.acronym-cell {
		white-space: nowrap;
	}
	.acronym-cell .entity-link {
		font-weight: 600;
	}
	.tutelles-col {
		width: 1%;
		min-width: 150px;
		white-space: nowrap;
	}
	.tutelles {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
</style>
