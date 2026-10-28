<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { columnLabels, filterLabels } from '#lib/labels.js';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { api, structures as structuresApi, errorMessage } from '#lib/api/index.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import { withBase } from '#lib/paths.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import { paramsToQuery, rorShortId, rorFullUrl } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import { STRUCTURE_TYPES } from '#lib/structureTypes.js';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import StructureDrawer from './StructureDrawer.svelte';
	import StructureFormModal from './StructureFormModal.svelte';
	import { API_SOURCES, ROR_FORMAT_ERROR, buildApiIds, normalizeRorId } from './types';

	import type { components } from '#lib/api/schema.js';
	type Structure = components['schemas']['StructureListItem'];
	type Perimeter = components['schemas']['PerimeterOut'];
	type ConfigItem = components['schemas']['ConfigItem'];

	const TYPE_LABELS = Object.fromEntries(STRUCTURE_TYPES.map((t) => [t.value, t.label]));

	let search = $state('');
	let currentSort = $state('acronym_asc');
	let selectedTypes = $state<string[]>([]);
	let selectedTutelles = $state<string[]>([]);
	// Identifiants de périmètre en chaîne, ou `none` pour les structures hors de tout périmètre. Seule la session admin change ce réglage.
	let selectedPerimeters = $state<string[]>([]);
	// Réglages par défaut : les types de la configuration, le périmètre des personnes. L'URL écrit seulement un écart à ces réglages ; `all` y désigne une sélection vide.
	let defaultTypes: string[] = [];
	let defaultPerimeters: string[] = [];

	const sameSelection = (a: string[], b: string[]) => a.length === b.length && a.every((v) => b.includes(v));
	const selectionToken = (selected: string[], defaults: string[]) =>
		sameSelection(selected, defaults) ? '' : selected.join(',') || 'all';
	const selectionFromToken = (token: string) => (token === 'all' ? [] : token.split(','));

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		const q = search.trim();
		if (q) params.set('search', q);
		if (selectedTypes.length) params.set('structure_type', selectedTypes.join(','));
		if (selectedTutelles.length) params.set('tutelle_id', selectedTutelles.join(','));
		if (selectedPerimeters.length) params.set('perimeter_id', selectedPerimeters.join(','));
		return params;
	}

	const list = usePaginatedFetch<Structure>({
		endpoint: '/api/structures',
		itemsKey: 'structures',
		perPage: 100,
		apiKey: 'structures-list',
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/structures/facets',
		apiKey: 'structures-facets',
		buildParams: buildFilterParams,
		facets: {
			types: { type: 'label_map', apiKey: 'types', labels: TYPE_LABELS },
			tutelles: { type: 'labeled', apiKey: 'tutelles' },
			perimeters: { type: 'labeled', apiKey: 'perimeters' },
		},
	});

	const url = useUrlFilters({
		basePath: () => '/structures',
		filters: {
			types: { type: 'single', urlKey: 'structure_type' },
			selectedTutelles: { type: 'string_array', urlKey: 'tutelle_id' },
			perimeters: { type: 'single', urlKey: 'perimeter_id' },
			search: { type: 'single', urlKey: 'search' },
			currentSort: { type: 'single', urlKey: 'sort', defaultValue: 'acronym_asc' },
			currentPage: { type: 'page', urlKey: 'page' },
		},
	});

	function syncUrl() {
		url.syncUrl(() => ({
			types: selectionToken(selectedTypes, defaultTypes),
			selectedTutelles,
			perimeters: selectionToken(selectedPerimeters, defaultPerimeters),
			search,
			currentSort,
			currentPage: list.page,
		}));
	}

	function onFilterChange() {
		list.page = 1;
		syncUrl();
		list.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(onFilterChange);

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		return withBase(`/api/structures/export.csv?${paramsToQuery(params)}`);
	}

	// Volet d'édition d'une structure, en session admin : ouvert tant que `?structure=<id>` figure dans l'URL.
	const drawer = useDrawerParam('structure', isAdmin);

	// Le type s'affiche dès que la liste mêle plusieurs types.
	const showTypeColumn = $derived(selectedTypes.length !== 1);

	function toggleSort(column: 'acronym' | 'name' | 'tutelles') {
		currentSort = nextSort(currentSort, column, 'asc');
		list.page = 1;
		syncUrl();
		list.load();
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
		for (const src of API_SOURCES) mApiIds[src] = '';
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
			list.load();
			drawer.open(created.id);
		} catch (e) {
			toast('Erreur: ' + errorMessage(e), 'error');
		}
	}

	onMount(async () => {
		const [config, perimeterList] = await Promise.all([
			api<ConfigItem[]>('/api/config'),
			api<Perimeter[]>('/api/perimeters'),
		]);
		defaultTypes = (config.find((c) => c.key === 'laboratories_display_types')?.value ?? ['labo']) as string[];
		const persons = perimeterList.find((p) => p.is_persons);
		defaultPerimeters = persons ? [String(persons.id)] : [];

		const restored = url.restoreFromUrl(page.url.searchParams);
		selectedTypes = restored.types ? selectionFromToken(restored.types as string) : defaultTypes;
		selectedPerimeters =
			restored.perimeters && isAdmin() ? selectionFromToken(restored.perimeters as string) : defaultPerimeters;
		if (restored.selectedTutelles) selectedTutelles = restored.selectedTutelles as string[];
		if (restored.search) search = restored.search as string;
		if (restored.currentSort) currentSort = restored.currentSort as string;
		if (restored.currentPage) list.page = restored.currentPage as number;

		await facets.load();
		list.load();
	});
</script>

<PageHeader title="Labos" hidden />

<ListToolbar bind:search placeholder="Rechercher par nom ou acronyme" onsearch={onSearchInput} {list} one="structure" many="structures" exportUrl={exportCsvUrl()}>
	{#snippet actions()}
		{#if isAdmin()}
			<button class="btn btn-primary btn-sm" onclick={openCreateModal}>+ Nouvelle</button>
		{/if}
	{/snippet}
	{#snippet filters()}
		<FacetDropdown label={filterLabels.types} options={facets.options.types} bind:selected={selectedTypes} onchange={onFilterChange} />
		<FacetDropdown label="Tutelles" options={facets.options.tutelles} searchable bind:selected={selectedTutelles} onchange={onFilterChange} />
		{#if isAdmin()}
			<FacetDropdown label="Périmètre" options={facets.options.perimeters} bind:selected={selectedPerimeters} onchange={onFilterChange} />
		{/if}
	{/snippet}
</ListToolbar>

<TableScroll>
<table class="data-table">
	<thead>
		<tr>
			{#if isAdmin()}<th class="row-actions"></th>{/if}
			{#if showTypeColumn}<th>{columnLabels.type}</th>{/if}
			<th class="sortable" class:active={sortDirection(currentSort, 'acronym') !== null} onclick={() => toggleSort('acronym')}>
				Acronyme
				<SortChevron direction={sortDirection(currentSort, 'acronym')} />
			</th>
			<th class="sortable" class:active={sortDirection(currentSort, 'name') !== null} onclick={() => toggleSort('name')}>
				Nom
				<SortChevron direction={sortDirection(currentSort, 'name')} />
			</th>
			<th class="sortable tutelles-col" class:active={sortDirection(currentSort, 'tutelles') !== null} onclick={() => toggleSort('tutelles')}>
				Tutelles
				<SortChevron direction={sortDirection(currentSort, 'tutelles')} />
			</th>
			<th>ROR</th>
			<th>Collection HAL</th>
		</tr>
	</thead>
	<tbody>
		{#if list.items.length === 0}
			<TableStatusRow loading={list.loading} error={list.error} colspan={5 + (showTypeColumn ? 1 : 0) + (isAdmin() ? 1 : 0)} emptyText="Aucune structure ne correspond aux filtres." />
		{/if}
		{#each list.items as s (s.id)}
			<tr class:active-row={s.id === drawer.id}>
				{#if isAdmin()}
					<td class="row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(s.id)} />
					</td>
				{/if}
				{#if showTypeColumn}
					<td><span class="structure-type structure-type-{s.type}">{s.type}</span></td>
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
							<span class="tutelle-tag">{structureLabel(t)}</span>
						{/each}
					</div>
				</td>
				<td>
					{#if s.ror_id}
						<a href={rorFullUrl(s.ror_id)} target="_blank" rel="noopener" class="id-badge">
							{rorShortId(s.ror_id)}
						</a>
					{/if}
				</td>
				<td>
					{#if s.hal_collection}
						<a href="https://hal.science/{s.hal_collection}" target="_blank" rel="noopener" class="id-badge">
							{s.hal_collection}
						</a>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>
</TableScroll>

<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />

{#if drawer.id !== null}
	<StructureDrawer id={drawer.id} onclose={() => drawer.open(null)} onchange={() => list.load()} onopenStructure={drawer.open} />
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
	.row-actions {
		width: 1%;
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
