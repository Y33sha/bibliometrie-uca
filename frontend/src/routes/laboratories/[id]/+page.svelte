<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { sanitizeTitle } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
	import { docTypeLabelsMap, oaLabelsMap, typeLabels } from '$lib/labels';

	const labId = $derived($page.params.id);
	const validTabs = ['publications', 'persons', 'addresses'] as const;
	type Tab = (typeof validTabs)[number];

	// --- Types ---
	interface Structure {
		id: number;
		code: string;
		name: string;
		acronym: string | null;
		type: string;
		ror_id: string | null;
		rnsr_id: string | null;
		hal_collection: string | null;
	}
	interface RelatedStructure {
		id: number;
		name: string;
		acronym: string | null;
		type: string;
		relation_type: string;
	}
	interface LabProfile {
		structure: Structure;
		parents: RelatedStructure[];
		children: RelatedStructure[];
	}
	interface Publication {
		id: number;
		title: string;
		pub_year: number | null;
		doi: string | null;
		doc_type: string | null;
		oa_status: string | null;
		journal: string | null;
		hal_id: string | null;
		openalex_id: string | null;
		labs: string | null;
	}
	interface PubResponse {
		total: number;
		page: number;
		pages: number;
		publications: Publication[];
	}
	interface LabPerson {
		id: number;
		last_name: string;
		first_name: string;
		role_title: string | null;
		department_name: string | null;
		has_rh: boolean;
		pub_count: number;
	}
	interface PersonsResponse {
		total_persons: number;
		page: number;
		per_page: number;
		pages: number;
		persons: LabPerson[];
		orphan_authorships: { hal: number; openalex: number; total: number };
	}
	interface LabAddress {
		id: number;
		raw_text: string;
		is_confirmed: boolean | null;
	}
	interface AddressesResponse {
		total: number;
		page: number;
		pages: number;
		addresses: LabAddress[];
	}

	// --- State ---
	let lab: Structure | null = $state(null);
	let parents: RelatedStructure[] = $state([]);
	let children: RelatedStructure[] = $state([]);
	let error = $state(false);

	const activeTab: Tab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab') as Tab | null;
			return t && validTabs.includes(t) ? t : 'publications';
		})()
	);

	// Publications tab
	let publications: Publication[] = $state([]);
	let pubTotal = $state(0);
	let pubPage = $state(1);
	let pubPages = $state(1);
	const pubPerPage = 50;

	// Pub filters
	let pubSearch = $state('');
	let debounceTimer: ReturnType<typeof setTimeout>;
	let selectedYears: string[] = $state([]);
	let sourceStates: Record<string, string> = $state({});
	let selectedDocTypes: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let yearOptions: FacetOption[] = $state([]);

	let docTypeOptions: FacetOption[] = $state([]);
	let oaOptions: FacetOption[] = $state([]);

	let pubsLoaded = $state(false);

	// Persons tab
	let persons: LabPerson[] = $state([]);
	let personsTotal = $state(0);
	let personsPage = $state(1);
	let personsPages = $state(1);
	let orphanStats = $state({ hal: 0, openalex: 0, total: 0 });
	let personsLoaded = $state(false);

	// Addresses tab
	let addresses: LabAddress[] = $state([]);
	let addrTotal = $state(0);
	let addrPage = $state(1);
	let addrPages = $state(1);
	let addrLoaded = $state(false);

	const tutelles = $derived(parents.filter((p) => p.relation_type === 'est_tutelle_de'));
	const partenaires = $derived(parents.filter((p) => p.relation_type === 'est_partenaire_de'));

	function rorShortId(rorId: string): string {
		return rorId.replace('https://ror.org/', '');
	}

	function buildPubFilterParams(): URLSearchParams {
		const params = new URLSearchParams({ lab_id: labId });
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		const sf = Object.entries(sourceStates).map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		return params;
	}

	async function loadPubFacets() {
		const params = buildPubFilterParams();
		const data = await api<{
			years: { value: number; count: number }[];
			doc_types: { value: string; count: number }[];
			oa_statuses: { value: string; count: number }[];
		}>('/api/publications/facets?' + params);
		yearOptions = data.years.map((y) => ({
			value: String(y.value), text: String(y.value), count: y.count
		}));
		docTypeOptions = data.doc_types.map((d) => ({
			value: d.value, text: docTypeLabelsMap[d.value] || d.value, count: d.count
		}));
		oaOptions = data.oa_statuses.map((o) => ({
			value: o.value, text: oaLabelsMap[o.value] || o.value, count: o.count
		}));
	}

	async function loadPublications() {
		const params = buildPubFilterParams();
		params.set('page', String(pubPage));
		params.set('per_page', String(pubPerPage));
		params.set('sort', 'year_desc');
		const q = pubSearch.trim();
		if (q) params.set('search', q);

		const data = await api<PubResponse>('/api/publications?' + params);
		publications = data.publications;
		pubTotal = data.total;
		pubPages = data.pages;
		pubPage = data.page;
		pubsLoaded = true;
	}

	function onFilterChange() {
		pubPage = 1;
		loadPublications();
		loadPubFacets();
	}

	function exportCsvUrl(): string {
		const params = buildPubFilterParams();
		params.set('sort', 'year_desc');
		const q = pubSearch.trim();
		if (q) params.set('search', q);
		return `${base}/api/publications/export.csv?${params}`;
	}

	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			pubPage = 1;
			loadPublications();
		}, 400);
	}

	async function loadPersons() {
		const params = new URLSearchParams({
			page: String(personsPage),
			per_page: '50'
		});
		const data = await api<PersonsResponse>(
			`/api/laboratories/${labId}/persons?${params}`
		);
		persons = data.persons;
		personsTotal = data.total_persons;
		personsPages = data.pages;
		personsPage = data.page;
		orphanStats = data.orphan_authorships;
		personsLoaded = true;
	}

	async function loadAddresses() {
		const params = new URLSearchParams({
			page: String(addrPage),
			per_page: '50'
		});
		const data = await api<AddressesResponse>(
			`/api/laboratories/${labId}/addresses?${params}`
		);
		addresses = data.addresses;
		addrTotal = data.total;
		addrPages = data.pages;
		addrPage = data.page;
		addrLoaded = true;
	}

	function switchTab(tab: Tab) {
		const url = new URL($page.url);
		if (tab === 'publications') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, noScroll: true });
		if (tab === 'publications' && !pubsLoaded) { loadPubFacets(); loadPublications(); }
		if (tab === 'persons' && !personsLoaded) loadPersons();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	onMount(async () => {
		try {
			const profileData = await api<LabProfile>(`/api/laboratories/${labId}`);
			lab = profileData.structure;
			parents = profileData.parents;
			children = profileData.children;
		} catch {
			error = true;
			return;
		}
		// Load data for the active tab (from URL)
		if (activeTab === 'persons') {
			loadPersons();
		} else if (activeTab === 'addresses') {
			loadAddresses();
		} else {
			loadPubFacets();
			loadPublications();
		}
	});
</script>

<svelte:head>
	<title>{lab ? (lab.acronym || lab.name) : 'Laboratoire'} — Bibliométrie UCA</title>
</svelte:head>

<!-- svelte-ignore a11y_invalid_attribute -->
<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>

{#if error}
	<div class="lab-header">
		<div class="no-results">Laboratoire introuvable</div>
	</div>
{:else if !lab}
	<div class="lab-header">
		<div class="loading">Chargement...</div>
	</div>
{:else}
	<!-- Header -->
	<div class="lab-header">
		<h1 class="lab-name">
			{lab.name}
			{#if lab.acronym}
				<span class="lab-acronym">({lab.acronym})</span>
			{/if}
		</h1>
		<div class="lab-meta">
			<div class="meta-row">
				{#if lab.ror_id}
					<span class="meta-label">ROR</span>
					<a href={lab.ror_id} target="_blank" rel="noopener" class="id-badge">
						{rorShortId(lab.ror_id)}
					</a>
				{/if}
				{#if lab.rnsr_id}
					<span class="meta-label">RNSR</span>
					<span class="id-badge">{lab.rnsr_id}</span>
				{/if}
				{#if lab.hal_collection}
					<span class="meta-label">HAL</span>
					<a
						href="https://hal.science/{lab.hal_collection}"
						target="_blank"
						rel="noopener"
						class="id-badge"
					>
						{lab.hal_collection}
					</a>
				{/if}
				{#if tutelles.length}
					<span class="meta-label">Tutelles</span>
					{#each tutelles as t (t.id)}
						<span class="tutelle-tag">{t.acronym || t.name}</span>
					{/each}
				{/if}
			</div>
			{#if partenaires.length}
				<div class="meta-row">
					<span class="meta-label">Partenaires</span>
					{#each partenaires as p (p.id)}
						<span class="partner-tag">{p.acronym || p.name}</span>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<!-- Tabs -->
	<div class="tabs">
		<button class="tab" class:active={activeTab === 'publications'} onclick={() => switchTab('publications')}>
			Publications
			{#if pubTotal}<span class="tab-count">{pubTotal}</span>{/if}
		</button>
		<button class="tab" class:active={activeTab === 'persons'} onclick={() => switchTab('persons')}>
			Personnes
			{#if personsLoaded}<span class="tab-count">{personsTotal}</span>{/if}
		</button>
		<button class="tab" class:active={activeTab === 'addresses'} onclick={() => switchTab('addresses')}>
			Adresses
			{#if addrLoaded}<span class="tab-count">{addrTotal}</span>{/if}
		</button>
	</div>

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<div class="toolbar">
				<input type="text" placeholder="Rechercher par titre..." bind:value={pubSearch} oninput={onSearchInput} />
				<FacetDropdown label="Années" options={yearOptions} bind:selected={selectedYears} onchange={onFilterChange} />
				<FacetDropdown label="Types" options={docTypeOptions} bind:selected={selectedDocTypes} onchange={onFilterChange} />
				<FacetDropdown label="Voies OA" options={oaOptions} bind:selected={selectedOa} onchange={onFilterChange} />
				<SourceFilterToggle bind:states={sourceStates} onchange={onFilterChange} />
				<span class="count">{pubTotal} publication{pubTotal > 1 ? 's' : ''}</span>
				<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
			</div>
			<table class="pub-table">
				<thead>
					<tr>
						<th style="width:40px">An.</th>
						<th>Titre</th>
						<th>Revue</th>
						<th style="width:80px">Liens</th>
						<th style="width:50px">OA</th>
						<th style="width:80px">Type</th>
					</tr>
				</thead>
				<tbody>
					{#if publications.length === 0}
						<tr><td colspan="6" class="no-results">Aucune publication</td></tr>
					{:else}
						{#each publications as p (p.id)}
							<tr>
								<td>{p.pub_year || ''}</td>
								<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
								<td class="journal-cell">{p.journal || ''}</td>
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
									{#if p.doi}
										<a href="https://doi.org/{p.doi}" target="_blank" rel="noopener" class="source-tag source-doi" title={p.doi}>
											<svg viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
								</td>
								<td>
									{#if p.oa_status && p.oa_status !== 'unknown'}
										<span class="oa-tag oa-{p.oa_status}">{p.oa_status}</span>
									{/if}
								</td>
								<td>
									<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
			<Pagination page={pubPage} pages={pubPages} onchange={(p) => { pubPage = p; loadPublications(); window.scrollTo(0, 0); }} />
		</div>
	{/if}

	<!-- Tab: Personnes -->
	{#if activeTab === 'persons'}
		<div class="tab-content">
			{#if orphanStats.total > 0}
				<a href="{base}/admin/authorships?lab={labId}&linked=no" class="orphan-banner">
					{orphanStats.total} authorship{orphanStats.total > 1 ? 's' : ''} non relié{orphanStats.total > 1 ? 'es' : 'e'} à une personne
					<span class="orphan-detail">(HAL : {orphanStats.hal}, OpenAlex : {orphanStats.openalex})</span>
				</a>
			{/if}
			<table>
				<thead>
					<tr>
						<th>Nom</th>
						<th>Fonction</th>
						<th>Département</th>
						<th style="width:80px">Publications</th>
					</tr>
				</thead>
				<tbody>
					{#if persons.length === 0}
						<tr><td colspan="4" class="no-results">Aucune personne trouvée</td></tr>
					{:else}
						{#each persons as p (p.id)}
							<tr>
								<td>
									<a href="{base}/persons/{p.id}" class="person-link">
										{p.first_name} <span class="person-last">{p.last_name}</span>
									</a>
									{#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
								</td>
								<td class="muted-cell">{p.role_title || ''}</td>
								<td class="muted-cell">{p.department_name || ''}</td>
								<td>{p.pub_count}</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
			<Pagination page={personsPage} pages={personsPages} onchange={(p) => { personsPage = p; loadPersons(); }} />
		</div>
	{/if}

	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			<table>
				<thead>
					<tr>
						<th>Adresse</th>
						<th style="width:80px">Statut</th>
					</tr>
				</thead>
				<tbody>
					{#if addresses.length === 0}
						<tr><td colspan="2" class="no-results">Aucune adresse</td></tr>
					{:else}
						{#each addresses as a (a.id)}
							<tr>
								<td class="addr-cell">{a.raw_text}</td>
								<td>
									{#if a.is_confirmed === true}
										<span class="status-tag confirmed">Confirmée</span>
									{:else}
										<span class="status-tag pending">En attente</span>
									{/if}
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
			<Pagination page={addrPage} pages={addrPages} onchange={(p) => { addrPage = p; loadAddresses(); }} />
		</div>
	{/if}
{/if}

<style>
	.back-link {
		display: inline-block;
		margin-bottom: 12px;
		font-size: 13px;
		color: var(--accent);
		text-decoration: none;
	}
	.back-link:hover { text-decoration: underline; }

	/* Header */
	.lab-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
		margin-bottom: 0;
	}
	.lab-name {
		font-size: 18px;
		font-weight: 600;
		margin: 0 0 10px;
	}
	.lab-acronym {
		font-size: 15px;
		color: var(--muted);
		font-weight: 400;
	}
	.lab-meta {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.meta-row {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		font-size: 13px;
	}
	.meta-label {
		font-size: 11px;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.3px;
	}
	.tutelle-tag, .partner-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 11px;
		white-space: nowrap;
	}
	.tutelle-tag { background: #e8f0f8; color: var(--accent); }
	.partner-tag { background: #f0efec; color: var(--muted); }
	.id-badge {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 11px;
		color: var(--accent);
		text-decoration: none;
		white-space: nowrap;
	}
	.id-badge:hover { background: #d4e4f3; }
	.id-badge { margin-right: 8px; }

	/* Tabs */
	.tabs {
		display: flex;
		gap: 0;
		background: var(--card);
		border-left: 1px solid var(--border);
		border-right: 1px solid var(--border);
		border-bottom: 1px solid var(--border);
		border-radius: 0 0 6px 6px;
		margin-bottom: 16px;
		overflow: hidden;
	}
	.tab {
		flex: 1;
		padding: 10px 16px;
		border: none;
		background: #f5f4f1;
		font-size: 13px;
		font-weight: 500;
		color: var(--muted);
		cursor: pointer;
		font-family: inherit;
		border-right: 1px solid var(--border);
		transition: background 0.15s, color 0.15s;
	}
	.tab:last-child { border-right: none; }
	.tab:hover { background: #eae9e5; color: var(--text); }
	.tab.active {
		background: var(--card);
		color: var(--accent);
		box-shadow: inset 0 -2px 0 var(--accent);
	}
	.tab-count {
		font-size: 11px;
		font-weight: 400;
		color: var(--muted);
		margin-left: 4px;
	}

	/* Toolbar */
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
		font-size: 13px;
		width: 220px;
	}
	.count {
		margin-left: auto;
		font-size: 12px;
		color: var(--muted);
	}
	.export-btn {
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 12px;
		color: var(--muted);
		text-decoration: none;
		cursor: pointer;
		white-space: nowrap;
	}
	.export-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}

	/* Shared table styles */
	.tab-content table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.tab-content thead th {
		background: #f5f4f1;
		padding: 8px 10px;
		text-align: left;
		font-size: 12px;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.tab-content tbody tr { border-bottom: 1px solid #f0efec; }
	.tab-content tbody tr:last-child { border-bottom: none; }
	.tab-content tbody tr:hover { background: #fafaf8; }
	.tab-content td {
		padding: 7px 10px;
		font-size: 13px;
		vertical-align: top;
	}

	/* Publications tab */
	.pub-title {
		font-weight: 500; color: var(--text);
		text-decoration: none; display: inline-block;
	}
	.pub-title:hover { color: var(--accent); text-decoration: underline; }
	.journal-cell { font-size: 12px; color: var(--muted); }
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
	.source-doi { background: #f0f0f0; }
	.source-doi:hover { background: #e0e0e0; }
	.source-placeholder { visibility: hidden; }
	.links-cell { white-space: nowrap; }
	.oa-tag {
		display: inline-block;
		font-size: 10px;
		padding: 1px 6px;
		border-radius: 8px;
		font-weight: 600;
	}
	:global(.oa-gold) { background: #fef3e0; color: #d4a017; }
	:global(.oa-hybrid) { background: #f3eef9; color: #8e6bbf; }
	:global(.oa-green) { background: #e6f4ec; color: #2a7d4f; }
	:global(.oa-bronze) { background: #fdf0e6; color: #b8733e; }
	:global(.oa-closed) { background: #e0e0e0; color: #555; }
	.type-label { font-size: 11px; color: var(--muted); }

	/* Persons tab */
	.person-link {
		color: var(--accent);
		text-decoration: none;
		font-weight: 500;
	}
	.person-link:hover { text-decoration: underline; }
	.person-last { font-weight: 600; }
	.rh-check {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 15px;
		height: 15px;
		border-radius: 50%;
		background: var(--accent, #3b82f6);
		color: white;
		font-size: 10px;
		font-weight: 700;
		margin-left: 4px;
		vertical-align: middle;
		line-height: 1;
	}
	.muted-cell { font-size: 12px; color: var(--muted); }
	.orphan-banner {
		display: block;
		background: #fef3e0;
		border: 1px solid #f0dca0;
		border-radius: 5px;
		padding: 8px 14px;
		margin-bottom: 12px;
		font-size: 13px;
		color: #8a6d1b;
		text-decoration: none;
	}
	.orphan-banner:hover {
		background: #fdecc8;
	}
	.orphan-detail {
		font-size: 12px;
		color: #a08530;
	}

	/* Addresses tab */
	.addr-cell {
		font-size: 12px;
		color: var(--muted);
		word-break: break-all;
	}
	.status-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 11px;
		font-weight: 500;
	}
	.status-tag.confirmed { background: #e6f4ec; color: #2a7d4f; }
	.status-tag.pending { background: #f0efec; color: var(--muted); }

	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
