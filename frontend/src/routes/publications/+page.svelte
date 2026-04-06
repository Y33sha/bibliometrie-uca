<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { sanitizeTitle, halDocUrl } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import { docTypeLabelsMap, oaLabelsMap, typeLabels } from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	interface Publication {
		id: number;
		title: string;
		pub_year: number | null;
		doi: string | null;
		doc_type: string | null;
		oa_status: string | null;
		journal: string | null;
		publisher_name: string | null;
		hal_id: string | null;
		openalex_id: string | null;
		wos_id: string | null;
		labs: string | null;
		apc: { amount: number; institution: string | null; lab_id: number | null; lab_acronym: string | null; budget_structure_id: number | null }[] | null;
	}

	// --- Filter state ---
	let search = $state('');
	let currentSort = $state('year_desc');
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let sourceStates: Record<string, string> = $state({});
	let selectedDocTypes: string[] = $state([]);
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
	const yearSortArrow = $derived(currentSort === 'year_asc' ? '↑' : '↓');
	const titleSortArrow = $derived(currentSort === 'title_desc' ? '↓' : '↑');
	const yearSortActive = $derived(currentSort === 'year_desc' || currentSort === 'year_asc');
	const titleSortActive = $derived(currentSort === 'title' || currentSort === 'title_desc');

	// --- Shared filter params builder ---
	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		if (selectedLabs.length) params.set('lab_id', selectedLabs.join(','));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
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
			selectedOa, selectedApc, search, currentSort,
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
		if (restored.sourceStates) sourceStates = restored.sourceStates as Record<string, string>;
		if (restored.selectedDocTypes) selectedDocTypes = restored.selectedDocTypes as string[];
		if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
		if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
		if (restored.search) search = restored.search as string;
		if (restored.currentSort) currentSort = restored.currentSort as string;
		if (restored.currentPage) pubs.page = restored.currentPage as number;
		if (restored.filterPublisherId) filterPublisherId = restored.filterPublisherId as string;
		if (restored.filterJournalId) filterJournalId = restored.filterJournalId as string;
		if (restored.filterPublisherName) filterPublisherName = restored.filterPublisherName as string;
		if (restored.filterJournalName) filterJournalName = restored.filterJournalName as string;

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

<div class="toolbar toolbar-card">
	<input type="text" placeholder="Rechercher par titre..." bind:value={search} oninput={onSearchInput} />
	<FacetDropdown label="Années" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />
	<FacetDropdown label="Laboratoires" options={facets.options.labs} searchable bind:selected={selectedLabs} onchange={onLabChange} />
	<FacetDropdown label="Types" options={facets.options.docTypes} bind:selected={selectedDocTypes} onchange={onFilterChange} />
	<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />
	<FacetDropdown label="APC" options={facets.options.apc} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />
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
			<th>Revue</th>
			<th style="width:80px">Type</th>
			<th style="width:40px" class="sortable" class:active={yearSortActive} onclick={toggleSortYear}>
				An. <span class="sort-arrow">{yearSortArrow}</span>
			</th>
			<th style="width:80px">Labo(s)</th>
			<th style="width:60px">APC</th>
			<th style="width:50px">OA</th>
			<th style="width:80px">Liens</th>
		</tr>
	</thead>
	<tbody>
		{#if pubs.items.length === 0}
			<tr><td colspan="8" class="no-results">Aucune publication trouvée</td></tr>
		{:else}
			{#each pubs.items as p (p.id)}
				<tr>
					<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
					<td class="journal-cell">{p.journal || ''}</td>
					<td>
						<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
					</td>
					<td>{p.pub_year || ''}</td>
					<td>
						{#each (p.labs || '').split(', ').filter(Boolean) as lab}
							<span class="lab-tag">{lab}</span>
						{/each}
					</td>
					<td class="apc-cell">
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
					</td>
					<td>
						{#if p.oa_status && p.oa_status !== 'unknown'}
							<span class="oa-tag oa-{p.oa_status}">{p.oa_status}</span>
						{/if}
					</td>
					<td class="links-cell">
						{#if p.hal_id}
							<a href={halDocUrl(p.hal_id)} target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
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
</style>
