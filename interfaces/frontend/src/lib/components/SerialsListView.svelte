<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { columnLabels, filterLabels } from '#lib/labels.js';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';

	import EntityFilter from '#lib/components/EntityFilter.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import PresenceFilterToggle from '#lib/components/PresenceFilterToggle.svelte';
	import SerialDrawer from '#lib/components/serials/SerialDrawer.svelte';
	import IssnBadge from '#lib/components/serials/IssnBadge.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { nextSort, sortDirection } from '#lib/sort.js';
	import { withBase } from '#lib/paths.js';
	import { paramsToQuery } from '#lib/utils.js';
	import { encodePresence, type PresenceStates } from '#lib/filterRegistry.js';
	import type { components } from '#lib/api/schema.js';

	type Serial = components['schemas']['SerialListItem'];
	type SerialListFacet = components['schemas']['SerialListFacet'];

	// Composant de liste de publications en série réutilisable. Utilisé par :
	// - `/journals` (mode autonome avec sync URL)
	// - `/publishers/[id]?tab=journals` (filtre `publisherId` fixe)
	// La session admin gagne, en tête de ligne, l'icône du volet d'édition de la publication en série ; sur `/journals`, elle gagne aussi la facette « Publications ».
	interface ExternalFilters {
		publisherId?: number;
	}

	let {
		apiKey = 'journals-list',
		externalFilters,
		urlSync = false,
		basePath = '/journals',
		perPage = 50,
		onchange,
	}: {
		apiKey?: string;
		externalFilters?: ExternalFilters;
		urlSync?: boolean;
		basePath?: string;
		perPage?: number;
		/** Appelé après chaque écriture du volet, après le rechargement de la liste. */
		onchange?: () => void;
	} = $props();

	// Volet d'édition d'une publication en série, en session admin : ouvert tant que `?serial=<id>` figure dans l'URL.
	const drawer = useDrawerParam('serial', isAdmin);

	// Éditeur imposé par le contexte : la facette et la colonne Éditeur portent alors la même valeur sur toutes les lignes, et sont masquées.
	const publisherFixed = $derived(externalFilters?.publisherId != null);

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('publications_desc');
	let selectedPublisher: string[] = $state([]); // 0 ou 1 identifiant d'éditeur
	let selectedSerialTypes: string[] = $state([]);
	let selectedOaModels: string[] = $state([]);
	// Facette « Listes » : présence exigée par liste ou classement, et niveaux cochés des classements.
	let listStates: PresenceStates = $state({});
	let checkedListLevels: string[] = $state([]);
	let listItems: { key: string; label: string; levels: { key: string; label: string }[] }[] = $state([]);
	let listCounts: Record<string, { yes: number; no: number }> = $state({});
	// Publications en série avec ou sans publication. Par défaut, celles qui en ont ; seule la session admin change ce réglage, sur `/journals`.
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
		const listFilter = encodePresence(listStates);
		if (listFilter) params.set('list_filter', listFilter);
		if (checkedListLevels.length) params.set('list_level', checkedListLevels.join(','));
		if (selectedPublications.length === 1) params.set('has_publications', selectedPublications[0]);
		const q = search.trim();
		if (q) params.set('search', q);
		return params;
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		return withBase(`/api/serials/export.csv?${paramsToQuery(params)}`);
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
			publications: { type: 'boolean', apiKey: 'publications', yesLabel: 'Avec', noLabel: 'Sans' },
		},
		afterLoad(data) {
			const lists = (data.lists ?? []) as SerialListFacet[];
			listItems = lists.map((l) => ({
				key: l.code,
				label: l.label,
				levels: l.levels.map((level) => ({ key: level.code, label: level.label })),
			}));
			listCounts = Object.fromEntries(
				lists.flatMap((l) => [
					[l.code, { yes: l.count, no: 0 }],
					...l.levels.map((level) => [level.code, { yes: level.count, no: 0 }]),
				]),
			);
		},
	});

	const url = useUrlFilters({
		basePath: () => basePath,
		filters: {
			selectedPublisher: { type: 'string_array', urlKey: 'publisher_id' },
			selectedSerialTypes: { type: 'string_array', urlKey: 'serial_type' },
			selectedOaModels: { type: 'string_array', urlKey: 'oa_model' },
			listStates: { type: 'source_states', urlKey: 'list_filter' },
			checkedListLevels: { type: 'string_array', urlKey: 'list_level' },
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
			listStates,
			checkedListLevels,
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
			if (restored.listStates) listStates = restored.listStates as PresenceStates;
			if (restored.checkedListLevels) checkedListLevels = restored.checkedListLevels as string[];
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

<ListToolbar bind:search placeholder="Rechercher par titre ou ISSN" onsearch={onSearchInput} list={serials} one="publication en série" many="publications en série" exportUrl={exportCsvUrl()}>
	{#snippet filters()}
		{#if !publisherFixed}
			<EntityFilter
				label={filterLabels.publisher}
				endpoint="/api/serials/facets"
				kind="publisher"
				buildParams={buildFilterParams}
				selected={selectedPublisher}
				onchange={(ids) => { selectedPublisher = ids; onFilterChange(); }}
			/>
		{/if}
		<FacetDropdown
			label={filterLabels.types}
			options={facets.options.serialTypes}
			bind:selected={selectedSerialTypes}
			onchange={onFilterChange}
		/>
		<PresenceFilterToggle
			label={filterLabels.lists}
			items={listItems}
			bind:states={listStates}
			bind:checkedLevels={checkedListLevels}
			counts={listCounts}
			onchange={onFilterChange}
		/>
		<FacetDropdown
			label="Modèles OA"
			options={facets.options.oaModels}
			bind:selected={selectedOaModels}
			onchange={onFilterChange}
		/>
		{#if isAdmin() && !publisherFixed}
			<FacetDropdown
				label="Publications"
				options={facets.options.publications}
				bind:selected={selectedPublications}
				onchange={onFilterChange}
			/>
		{/if}
	{/snippet}
</ListToolbar>

<TableScroll>
<table class="data-table journals-table">
	<thead>
		<tr>
			{#if isAdmin()}<th class="row-actions"></th>{/if}
			<th class="diamond-col" aria-label="Revue diamant"></th>
			<th class="sortable" onclick={() => setSort('title')}>
				{columnLabels.title} <SortChevron direction={sortDirection(currentSort, 'title')} />
			</th>
			<th>ISSN</th>
			{#if !publisherFixed}
				<th class="sortable" onclick={() => setSort('publisher')}>
					{columnLabels.publisher} <SortChevron direction={sortDirection(currentSort, 'publisher')} />
				</th>
			{/if}
			<th>{columnLabels.type}</th>
			<th class="num sortable" onclick={() => setSort('publications')}>
				{columnLabels.publications} <SortChevron direction={sortDirection(currentSort, 'publications')} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#each serials.items as j (j.id)}
			<tr class:active-row={j.id === drawer.id}>
				{#if isAdmin()}
					<td class="row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => drawer.open(j.id)} />
					</td>
				{/if}
				<td class="diamond-col">
					{#if j.oa_model === 'diamond'}
						<span class="diamond" title="Revue diamant&nbsp;: open access sans frais de publication" aria-label="Revue diamant">
							<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
								<path d="M6 3h12l4 6-10 13L2 9Z" />
								<path d="M11 3 8 9l4 13 4-13-3-6" />
								<path d="M2 9h20" />
							</svg>
						</span>
					{/if}
				</td>
				<td>
					<a href={resolve(`journals/${j.id}`)} class="entity-link">{j.title}</a>
					{#if j.is_in_doaj}
						{#if j.doaj_url}
							<a class="badge-doaj" href={j.doaj_url} target="_blank" rel="noopener" title="Fiche DOAJ (nouvel onglet)">DOAJ</a>
						{:else}
							<span class="badge-doaj" title="Indexée dans DOAJ">DOAJ</span>
						{/if}
					{/if}				</td>
				<td><div class="id-list">{#each j.issns as issn (issn)}<IssnBadge {issn} />{/each}</div></td>
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
			</tr>
		{/each}
		{#if serials.items.length === 0}
			<TableStatusRow loading={serials.loading} error={serials.error} colspan={(publisherFixed ? 5 : 6) + (isAdmin() ? 1 : 0)} emptyText="Aucune publication en série ne correspond aux filtres." />
		{/if}
	</tbody>
</table>
</TableScroll>

<Pagination
	page={serials.page}
	pages={serials.pages}
	onchange={(p) => {
		serials.page = p;
		syncUrl();
		serials.load();
	}}
/>

{#if drawer.id !== null}
	<SerialDrawer
		id={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={() => {
			serials.load();
			facets.load();
			onchange?.();
		}}
	/>
{/if}

<style>
	.journals-table { min-width: 660px; }
	.journals-table td.num { color: var(--muted); }
	.diamond-col { width: 1.5rem; padding-right: 0; }
	.diamond { display: inline-flex; color: var(--diamond-text); vertical-align: middle; }
	.muted { color: var(--muted); }
</style>
