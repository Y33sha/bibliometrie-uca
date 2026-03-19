<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { sanitizeTitle } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
	import { docTypeLabelsMap, oaLabelsMap, typeLabels } from '$lib/labels';

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

	interface PubResponse {
		total: number;
		page: number;
		pages: number;
		per_page: number;
		publications: Publication[];
	}

	// --- State ---
	let publications: Publication[] = $state([]);
	let total = $state(0);
	let currentPage = $state(1);
	let totalPages = $state(1);
	const perPage = 100;

	let search = $state('');
	let debounceTimer: ReturnType<typeof setTimeout>;
	let currentSort = $state('year_desc');

	// Facet selections
	let selectedYears: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let sourceStates: Record<string, string> = $state({});
	let selectedDocTypes: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);

	// Facet options (dynamic)
	let yearOptions: FacetOption[] = $state([]);
	let labOptions: FacetOption[] = $state([]);
	let apcOptions: FacetOption[] = $state([]);

	// Filter from stats page (publisher/journal)
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

	// Facet options (dynamic)
	let docTypeOptions: FacetOption[] = $state([]);
	let oaOptions: FacetOption[] = $state([]);
	let sourceCounts: Record<string, number> = $state({});

	// Sort display
	const yearSortArrow = $derived(currentSort === 'year_asc' ? '↑' : '↓');
	const titleSortArrow = $derived(currentSort === 'title_desc' ? '↓' : '↑');
	const yearSortActive = $derived(currentSort === 'year_desc' || currentSort === 'year_asc');
	const titleSortActive = $derived(currentSort === 'title' || currentSort === 'title_desc');

	function toggleSortYear() {
		currentSort = currentSort === 'year_desc' ? 'year_asc' : 'year_desc';
		currentPage = 1;
		syncUrl();
		loadPublications();
	}

	function toggleSortTitle() {
		currentSort = currentSort === 'title' ? 'title_desc' : 'title';
		currentPage = 1;
		syncUrl();
		loadPublications();
	}

	function syncUrl() {
		const p = new URLSearchParams();
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		if (selectedLabs.length) p.set('lab_id', selectedLabs.join(','));
		const sf = Object.entries(sourceStates).map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) p.set('source_filter', sf);
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (filterPublisherId) { p.set('publisher_id', filterPublisherId); if (filterPublisherName) p.set('publisher_name', filterPublisherName); }
		if (filterJournalId) { p.set('journal_id', filterJournalId); if (filterJournalName) p.set('journal_name', filterJournalName); }
		if (search.trim()) p.set('search', search.trim());
		if (currentSort !== 'year_desc') p.set('sort', currentSort);
		if (currentPage > 1) p.set('page', String(currentPage));
		const qs = p.toString();
		history.replaceState(history.state, '', base + '/publications' + (qs ? '?' + qs : ''));
	}

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		if (selectedLabs.length) params.set('lab_id', selectedLabs.join(','));
		const sf = Object.entries(sourceStates).map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) params.set('has_apc', selectedApc.join(','));
		if (filterPublisherId) params.set('publisher_id', filterPublisherId);
		if (filterJournalId) params.set('journal_id', filterJournalId);
		return params;
	}

	async function loadFacets() {
		const params = buildFilterParams();
		const data = await api<{
			years: { value: number; count: number }[];
			labs: { value: number; label: string; count: number }[];
			no_lab_count: number;
			doc_types: { value: string; count: number }[];
			oa_statuses: { value: string; count: number }[];
			source_counts: Record<string, number>;
			apc: { value: string; text: string; count: number }[];
		}>('/api/publications/facets?' + params);
		yearOptions = data.years.map((y) => ({
			value: String(y.value), text: String(y.value), count: y.count
		}));
		labOptions = [
			{ value: 'none', text: '— Aucun labo —', count: data.no_lab_count },
			...data.labs.map((l) => ({
				value: String(l.value), text: l.label, count: l.count
			}))
		];
		docTypeOptions = data.doc_types.map((d) => ({
			value: d.value, text: docTypeLabelsMap[d.value] || d.value, count: d.count
		}));
		oaOptions = data.oa_statuses.map((o) => ({
			value: o.value, text: oaLabelsMap[o.value] || o.value, count: o.count
		}));
		sourceCounts = data.source_counts || {};
		if (data.apc) {
			apcOptions = data.apc.map(a => ({ value: a.value, text: a.text, count: a.count }));
		}
	}

	async function loadPublications() {
		const params = buildFilterParams();
		params.set('page', String(currentPage));
		params.set('per_page', String(perPage));
		params.set('sort', currentSort);
		const q = search.trim();
		if (q) params.set('search', q);

		const data = await api<PubResponse>('/api/publications?' + params);
		publications = data.publications;
		total = data.total;
		totalPages = data.pages;
		currentPage = data.page;
	}

	function onFilterChange() {
		currentPage = 1;
		syncUrl();
		loadPublications();
		loadFacets();
	}

	function onLabChange(newSelection: string[]) {
		const hadNone = selectedLabs.includes('none');
		const hasNone = newSelection.includes('none');
		if (hasNone && !hadNone) {
			selectedLabs = ['none'];
		} else if (hasNone && newSelection.length > 1) {
			selectedLabs = newSelection.filter((v) => v !== 'none');
		} else {
			selectedLabs = newSelection;
		}
		currentPage = 1;
		syncUrl();
		loadPublications();
		loadFacets();
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', currentSort);
		const q = search.trim();
		if (q) params.set('search', q);
		return `${base}/api/publications/export.csv?${params}`;
	}

	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			currentPage = 1;
			syncUrl();
			loadPublications();
		}, 400);
	}

	function onPageChange(p: number) {
		currentPage = p;
		syncUrl();
		loadPublications();
		window.scrollTo(0, 0);
	}

	onMount(async () => {
		// Read URL params for external filters (from stats page)
		const urlParams = $page.url.searchParams;
		filterPublisherId = urlParams.get('publisher_id');
		filterJournalId = urlParams.get('journal_id');
		filterPublisherName = urlParams.get('publisher_name');
		filterJournalName = urlParams.get('journal_name');

		// Pre-select facets from URL
		if (urlParams.get('year')) selectedYears = urlParams.get('year')!.split(',');
		if (urlParams.get('doc_type')) selectedDocTypes = urlParams.get('doc_type')!.split(',');
		if (urlParams.get('oa_status')) selectedOa = urlParams.get('oa_status')!.split(',');
		if (urlParams.get('has_apc')) selectedApc = urlParams.get('has_apc')!.split(',');
		if (urlParams.get('lab_id')) selectedLabs = urlParams.get('lab_id')!.split(',');
		if (urlParams.get('source_filter')) {
			const states: Record<string, string> = {};
			for (const v of urlParams.get('source_filter')!.split(',')) {
				const m = v.match(/^(\w+)_(yes|no)$/);
				if (m) states[m[1]] = m[2];
			}
			sourceStates = states;
		}
		if (urlParams.get('search')) search = urlParams.get('search')!;
		if (urlParams.get('sort')) currentSort = urlParams.get('sort')!;
		if (urlParams.get('page')) currentPage = Number(urlParams.get('page')) || 1;

		await loadFacets();
		loadPublications();
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

<div class="toolbar">
	<input type="text" placeholder="Rechercher par titre..." bind:value={search} oninput={onSearchInput} />
	<FacetDropdown label="Années" options={yearOptions} bind:selected={selectedYears} onchange={onFilterChange} />
	<FacetDropdown label="Laboratoires" options={labOptions} searchable bind:selected={selectedLabs} onchange={onLabChange} />
	<FacetDropdown label="Types" options={docTypeOptions} bind:selected={selectedDocTypes} onchange={onFilterChange} />
	<FacetDropdown label="Voies OA" options={oaOptions} bind:selected={selectedOa} onchange={onFilterChange} />
	<FacetDropdown label="APC" options={apcOptions} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />
	<SourceFilterToggle bind:states={sourceStates} counts={sourceCounts} onchange={onFilterChange} />
	<span class="count">{total} publication{total > 1 ? 's' : ''}</span>
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
		{#if publications.length === 0}
			<tr><td colspan="8" class="no-results">Aucune publication trouvée</td></tr>
		{:else}
			{#each publications as p (p.id)}
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
							<a href="https://hal.science/{p.hal_id}" target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
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

<Pagination page={currentPage} pages={totalPages} onchange={onPageChange} />

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

	.toolbar {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 12px;
		padding: 10px 14px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.toolbar input[type='text'] {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.95rem;
		width: 280px;
	}
	.count {
		margin-left: auto;
		font-size: 0.85rem;
		color: var(--muted);
	}
	.export-btn {
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 0.85rem;
		color: var(--muted);
		text-decoration: none;
		cursor: pointer;
		white-space: nowrap;
	}
	.export-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

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

	.sortable {
		cursor: pointer;
		user-select: none;
	}
	.sortable:hover { color: var(--accent); }
	.sort-arrow { font-size: 0.8rem; opacity: 0.3; }
	.sortable.active .sort-arrow { opacity: 1; color: var(--accent); }

	.pub-title {
		font-weight: 500; color: var(--text); max-width: 500px;
		text-decoration: none; display: inline-block;
	}
	.pub-title:hover { color: var(--accent); text-decoration: underline; }
	.journal-cell { font-size: 0.85rem; color: var(--muted); }

	.source-tag {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		text-decoration: none;
		margin-right: 3px;
		vertical-align: middle;
		transition: transform 0.1s;
	}
	.source-tag:hover { transform: scale(1.15); }
	.source-tag img, .source-tag :global(svg) { width: 14px; height: 14px; display: block; }
	.source-hal { background: #e8f0f8; }
	.source-hal:hover { background: #d0e3f4; }
	.source-oa { background: #fef3e0; }
	.source-oa:hover { background: #fde8c8; }
	.source-wos { background: #e8e0f8; }
	.source-wos:hover { background: #d8c8f4; }
	.wos-label { font-size: 11px; font-weight: 700; color: #5a3d8a; line-height: 14px; }
	.source-doi { background: #f0f0f0; }
	.source-doi:hover { background: #e0e0e0; }
	.source-placeholder { visibility: hidden; }
	.links-cell { white-space: nowrap; }

	.lab-tag {
		display: inline-block;
		font-size: 0.8rem;
		padding: 1px 7px;
		border-radius: 10px;
		background: #e8f0f8;
		color: var(--accent);
		font-weight: 500;
	}

	.apc-cell { text-align: right; white-space: nowrap; }
	.apc-tag {
		display: inline-block;
		font-size: 0.75rem;
		padding: 1px 5px;
		border-radius: 3px;
		background: #e8f5e9;
		color: #2e7d32;
		font-weight: 500;
		cursor: default;
	}
	.apc-other { background: #f0f0f0; color: #888; }

	.oa-tag {
		display: inline-block;
		font-size: 0.7rem;
		padding: 1px 6px;
		border-radius: 8px;
		font-weight: 600;
	}
	:global(.oa-gold) { background: #fef3e0; color: #d4a017; }
	:global(.oa-diamond) { background: #e0f2f7; color: #0288a8; }
	:global(.oa-hybrid) { background: #f3eef9; color: #8e6bbf; }
	:global(.oa-green) { background: #e6f4ec; color: #2a7d4f; }
	:global(.oa-bronze) { background: #fdf0e6; color: #b8733e; }
	:global(.oa-closed) { background: #e0e0e0; color: #555; }

	.type-label { font-size: 0.8rem; color: var(--muted); }
	.no-results { text-align: center; padding: 40px; color: var(--muted); }
</style>
