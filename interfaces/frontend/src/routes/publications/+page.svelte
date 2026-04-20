<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { sanitizeTitle, halDocUrl, scanrPubUrl } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import { docTypeLabelsMap, oaLabelsMap, typeLabels } from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import { useColumnVisibility } from '$lib/composables/useColumnVisibility.svelte';
	import ColumnMenu from '$lib/components/ColumnMenu.svelte';

	import type { components } from '$lib/api/schema';
	type Publication = components['schemas']['PublicationListItem'];

	// --- Column visibility ---
	const cv = useColumnVisibility([
		{ key: 'title',   label: 'Titre',    fixed: true },
		{ key: 'journal', label: 'Revue' },
		{ key: 'type',    label: 'Type' },
		{ key: 'year',    label: 'Année' },
		{ key: 'labs',    label: 'Labo(s)' },
		{ key: 'apc',     label: 'APC' },
		{ key: 'oa',      label: 'OA' },
		{ key: 'oa_path', label: 'Voie OA' },
		{ key: 'links',   label: 'Liens',    fixed: true },
	], ['apc', 'oa_path']);
	const col = cv.col;

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('year_desc');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let sourceStates = $state<Record<string, 'all' | 'yes' | 'no'>>({});
	let selectedDocTypes: string[] = $state([]);
	let selectedAccess: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let selectedCountries: string[] = $state([]);

	// External filters (from stats page)
	let filterPublisherId: string | null = $state(null);
	let filterJournalId: string | null = $state(null);
	let filterPublisherName: string | null = $state(null);
	let filterJournalName: string | null = $state(null);

	const hasExternalFilter = $derived(!!filterPublisherId || !!filterJournalId);

	const filterBannerText = $derived.by(() => {
		const parts: string[] = [];
		if (filterPublisherName) parts.push('éditeur = ' + filterPublisherName);
		else if (filterPublisherId) parts.push('éditeur #' + filterPublisherId);
		if (filterJournalName) parts.push('revue = ' + filterJournalName);
		else if (filterJournalId) parts.push('revue #' + filterJournalId);
		return parts.join(', ');
	});

	const cleanFilterUrl = $derived.by(() => {
		const keep = new URLSearchParams($page.url.search);
		keep.delete('publisher_id');
		keep.delete('journal_id');
		keep.delete('publisher_name');
		keep.delete('journal_name');
		const qs = keep.toString();
		return base + '/publications' + (qs ? '?' + qs : '');
	});

	// Sort display
	const yearSortArrow = $derived(currentSort === 'year_asc' ? '↑' : currentSort === 'year_desc' ? '↓' : '');
	const titleSortArrow = $derived(currentSort === 'title' ? '↑' : currentSort === 'title_desc' ? '↓' : '');
	const apcSortArrow = $derived(currentSort === 'apc_asc' ? '↑' : currentSort === 'apc_desc' ? '↓' : '');
	const yearSortActive = $derived(currentSort === 'year_desc' || currentSort === 'year_asc');
	const titleSortActive = $derived(currentSort === 'title' || currentSort === 'title_desc');
	const apcSortActive = $derived(currentSort === 'apc_desc' || currentSort === 'apc_asc');

	// --- Shared filter params builder ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('excluded_doc_type', 'ongoing_thesis');
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		if (selectedLabs.length) params.set('lab_id', selectedLabs.join(','));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedAccess.length) params.set('access', selectedAccess.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) params.set('has_apc', selectedApc.join(','));
		if (selectedCountries.length) params.set('country', selectedCountries.join(','));
		if (filterPublisherId) params.set('publisher_id', filterPublisherId);
		if (filterJournalId) params.set('journal_id', filterJournalId);
		return params;
	}

	// --- Composables ---
	const pubs = usePaginatedFetch<Publication>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		perPage: 100,
		apiKey: 'pub-list',
		buildParams() {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/publications/facets',
		apiKey: 'pub-facets',
		buildParams: buildFilterParams,
		sourceCountsKey: 'source_counts',
		facets: {
			years:     { type: 'simple',      apiKey: 'years' },
			labs:      { type: 'labeled',     apiKey: 'labs' },
			docTypes:  { type: 'label_map',   apiKey: 'doc_types',   labels: docTypeLabelsMap },
			access:    { type: 'passthrough', apiKey: 'access' },
			oa:        { type: 'label_map',   apiKey: 'oa_statuses', labels: oaLabelsMap },
			apc:       { type: 'passthrough', apiKey: 'apc' },
			countries: { type: 'passthrough', apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.text} (${c.value.toUpperCase()})`, count: c.count }) },
		},
		afterLoad(data, options) {
			options.labs = [
				{ value: 'none', text: '— Aucun labo —', count: (data.no_lab_count as number) ?? 0 },
				...options.labs,
			];
		},
	});

	const url = useUrlFilters({
		basePath: '/publications',
		filters: {
			selectedYears:     { type: 'string_array',  urlKey: 'year' },
			selectedLabs:      { type: 'string_array',  urlKey: 'lab_id' },
			sourceStates:      { type: 'source_states', urlKey: 'source_filter' },
			selectedDocTypes:  { type: 'string_array',  urlKey: 'doc_type' },
			selectedAccess:    { type: 'string_array',  urlKey: 'access' },
			selectedOa:        { type: 'string_array',  urlKey: 'oa_status' },
			selectedApc:       { type: 'string_array',  urlKey: 'has_apc' },
			search:            { type: 'single',        urlKey: 'search' },
			currentSort:       { type: 'single',        urlKey: 'sort', defaultValue: 'year_desc' },
			currentPage:       { type: 'page',          urlKey: 'page' },
			filterPublisherId: { type: 'single',        urlKey: 'publisher_id' },
			filterJournalId:   { type: 'single',        urlKey: 'journal_id' },
			filterPublisherName: { type: 'single',      urlKey: 'publisher_name' },
			filterJournalName:   { type: 'single',      urlKey: 'journal_name' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		url.syncUrl(() => ({
			selectedYears, selectedLabs, sourceStates, selectedDocTypes,
			selectedAccess, selectedOa, selectedApc, search, currentSort,
			currentPage: pubs.page,
			filterPublisherId, filterJournalId, filterPublisherName, filterJournalName,
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
		else if (hasNone && newSelection.length > 1) selectedLabs = newSelection.filter((v) => v !== 'none');
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

	function toggleSortTitle() {
		currentSort = currentSort === 'title' ? 'title_desc' : 'title';
		onFilterChange();
	}

	function toggleSortApc() {
		currentSort = currentSort === 'apc_desc' ? 'apc_asc' : 'apc_desc';
		onFilterChange();
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		const q = search.trim();
		if (q) params.set('search', q);
		return `${base}/api/publications/export.csv?${params}`;
	}

	onMount(async () => {
		const restored = url.restoreFromUrl($page.url.searchParams);
		if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
		if (restored.selectedLabs) selectedLabs = restored.selectedLabs as string[];
		if (restored.sourceStates) sourceStates = restored.sourceStates as Record<string, 'all' | 'yes' | 'no'>;
		if (restored.selectedDocTypes) selectedDocTypes = restored.selectedDocTypes as string[];
		if (restored.selectedAccess) selectedAccess = restored.selectedAccess as string[];
		if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
		if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
		if (restored.search) search = restored.search as string;
		if (restored.currentSort) currentSort = restored.currentSort as string;
		if (restored.currentPage) pubs.page = restored.currentPage as number;
		if (restored.filterPublisherId) filterPublisherId = restored.filterPublisherId as string;
		if (restored.filterJournalId) filterJournalId = restored.filterJournalId as string;
		if (restored.filterPublisherName) filterPublisherName = restored.filterPublisherName as string;
		if (restored.filterJournalName) filterJournalName = restored.filterJournalName as string;

		// Forcer l'affichage des colonnes liées aux filtres actifs
		const needed: string[] = [];
		if (selectedOa.length || selectedAccess.length) needed.push('oa', 'oa_path');
		if (selectedApc.length) needed.push('apc');
		if (filterPublisherId || filterJournalId) needed.push('journal');
		if (selectedDocTypes.length) needed.push('type');
		if (needed.length) cv.ensure(needed);

		await facets.load();
		pubs.load();
	});
</script>

<svelte:head>
	<title>Publications — Bibliométrie UCA</title>
</svelte:head>

{#if hasExternalFilter}
	<div class="filter-banner">
		Filtre actif : {filterBannerText} — <a href={cleanFilterUrl} onclick={(e) => {
			e.preventDefault();
			filterPublisherId = null;
			filterJournalId = null;
			filterPublisherName = null;
			filterJournalName = null;
			onFilterChange();
		}}>Supprimer le filtre</a>
	</div>
{/if}

<div class="toolbar toolbar-card toolbar-sticky">
	<input type="text" placeholder="Rechercher par titre..." bind:value={search} oninput={onSearchInput} />
	{#if col('year')}<FacetDropdown label="Années" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />{/if}
	{#if col('labs')}<FacetDropdown label="Laboratoires" options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onLabChange} />{/if}
	{#if col('type')}<FacetDropdown label="Types" options={facets.options.docTypes} bind:selected={selectedDocTypes} onchange={onFilterChange} />{/if}
	{#if col('oa')}<FacetDropdown label="Accès" options={facets.options.access} bind:selected={selectedAccess} onchange={onFilterChange} />{/if}
	{#if col('oa_path')}<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />{/if}
	{#if col('apc')}<FacetDropdown label="APC" options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />{/if}
	<FacetDropdown label="Pays" options={facets.options.countries} searchable bind:selected={selectedCountries} onchange={onFilterChange} />
	<SourceFilterToggle bind:states={sourceStates} counts={facets.sourceCounts} onchange={onFilterChange} />
	<span class="count">{pubs.total} publication{pubs.total > 1 ? 's' : ''}</span>
	<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
</div>

<table class="pub-table">
	<thead>
		<tr>
			<th class="sortable" class:active={titleSortActive} onclick={toggleSortTitle}>
				Titre <span class="sort-arrow">{titleSortArrow}</span>
			</th>
			{#if col('journal')}<th>Revue</th>{/if}
			{#if col('type')}<th style="width:80px">Type</th>{/if}
			{#if col('year')}<th style="width:40px" class="sortable" class:active={yearSortActive} onclick={toggleSortYear}>
				An. <span class="sort-arrow">{yearSortArrow}</span>
			</th>{/if}
			{#if col('labs')}<th style="width:80px">Labo(s)</th>{/if}
			{#if col('apc')}<th style="width:60px" class="sortable" class:active={apcSortActive} onclick={toggleSortApc}>
				APC <span class="sort-arrow">{apcSortArrow}</span>
			</th>{/if}
			{#if col('oa')}<th style="width:75px" title="Open Access">OA</th>{/if}
			{#if col('oa_path')}<th style="width:60px">Voie OA</th>{/if}
			<th style="width:80px" class="col-menu-th">
				<ColumnMenu columns={cv.columns} visibleColumns={cv.visibleColumns}
					showMenu={cv.showMenu}
					onToggle={cv.toggle}
					onClose={() => cv.showMenu = false}
					onOpen={() => cv.showMenu = !cv.showMenu} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#if pubs.items.length === 0}
			<tr><td colspan={cv.visibleColumns.length} class="no-results">Aucune publication trouvée</td></tr>
		{:else}
			{#each pubs.items as p (p.id)}
				<tr>
					<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
					{#if col('journal')}<td class="journal-cell">{p.journal || ''}</td>{/if}
					{#if col('type')}<td>
						<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
					</td>{/if}
					{#if col('year')}<td>{p.pub_year || ''}</td>{/if}
					{#if col('labs')}<td>
						{#each p.lab_items || [] as lab}
							<a href="{base}/laboratories/{lab.id}" class="lab-tag">{lab.label}</a>
						{/each}
					</td>{/if}
					{#if col('apc')}<td class="apc-cell">
						{#if p.apc}
							{@const ucaApc = p.apc.filter(a => a.budget_structure_id === 169)}
							{#if ucaApc.length > 0}
								<span class="apc-tag" title={ucaApc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.lab_acronym || 'UCA'})`).join('\n')}>
									{Math.round(ucaApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{:else}
								<span class="apc-tag apc-other" title={p.apc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.institution || '?'})`).join('\n')}>
									{Math.round(p.apc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
								</span>
							{/if}
						{/if}
					</td>{/if}
					{#if col('oa')}<td class="oa-lock-cell">
						{#if p.oa_status && !['unknown', 'closed'].includes(p.oa_status)}
							<span class="oa-lock-badge oa-lock-open">
								<img src="{base}/lock-open.svg" alt="Open Access" class="oa-lock" title="Open Access ({p.oa_status})" />
								<span class="oa-lock-label">ouvert</span>
							</span>
						{:else}
							<span class="oa-lock-badge oa-lock-closed">
								<img src="{base}/lock-closed.svg" alt="Closed" class="oa-lock" title="Accès fermé" />
								<span class="oa-lock-label">fermé</span>
							</span>
						{/if}
					</td>{/if}
					{#if col('oa_path')}<td>
						{#if p.oa_status && p.oa_status !== 'unknown'}
							<span class="oa-tag oa-{p.oa_status}">{p.oa_status}</span>
						{/if}
					</td>{/if}
					<td class="links-cell">
						{#if p.hal_id}
							<a href={halDocUrl(p.hal_id, p.oa_status)} target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
								<img src="https://hal.science/favicon.ico" alt="HAL" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.openalex_id}
							<a href="https://openalex.org/{p.openalex_id}" target="_blank" rel="noopener" class="source-tag source-oa" title="OpenAlex: {p.openalex_id}">
								<img src="https://raw.githubusercontent.com/ourresearch/openalex-gui/refs/heads/master/public/favicon.png" alt="OA" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.scanr_id}
							<a href={scanrPubUrl(p.scanr_id)} target="_blank" rel="noopener" class="source-tag source-scanr" title="ScanR: {p.scanr_id}">
								<img src="{base}/scanr-icon.svg" alt="ScanR" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.wos_id}
							<a href="https://www.webofscience.com/wos/woscc/full-record/{p.wos_id}" target="_blank" rel="noopener" class="source-tag source-wos" title="WoS: {p.wos_id}">
								<img src="https://www.webofscience.com/favicon.ico" alt="WoS" />
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
						{#if p.doi}
							<a href="https://doi.org/{p.doi}" target="_blank" rel="noopener" class="source-tag source-doi" title={p.doi}>
								<svg viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
									<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
									<polyline points="15 3 21 3 21 9"/>
									<line x1="10" y1="14" x2="21" y2="3"/>
								</svg>
							</a>
						{:else}
							<span class="source-tag source-placeholder"></span>
						{/if}
					</td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>

<Pagination page={pubs.page} pages={pubs.pages} onchange={(p) => { pubs.goToPage(p); syncUrl(); }} />

<style>
	.filter-banner {
		background: #e8f0f8;
		border: 1px solid #c4d8ed;
		border-radius: 5px;
		padding: 8px 14px;
		margin-bottom: 12px;
		font-size: 0.95rem;
		color: #2c3e50;
	}
	.filter-banner a { color: var(--accent); }
	.toolbar input[type='text'] { width: 280px; }
	.pub-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.pub-table th {
		background: #f5f4f1;
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.pub-table td {
		padding: 7px 10px;
		border-bottom: 1px solid #f0efec;
		font-size: 0.95rem;
		vertical-align: top;
	}
	.pub-table tr:hover td { background: #fafaf8; }
	.col-menu-th { position: relative; }
</style>
