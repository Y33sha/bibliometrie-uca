<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { sanitizeTitle } from '$lib/utils';
	import { Chart, registerables } from 'chart.js';
	Chart.register(...registerables);
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
	import { docTypeLabelsMap, oaLabelsMap, typeLabels } from '$lib/labels';

	const labId = $derived($page.params.id);
	let canGoBack = $state(false);
	const validTabs = ['dashboard', 'publications', 'persons', 'addresses'] as const;
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
		wos_id: string | null;
		labs: string | null;
		apc: { amount: number; institution: string | null; lab_id: number | null; lab_acronym: string | null; budget_structure_id: number | null }[] | null;
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
			return t && validTabs.includes(t) ? t : 'dashboard';
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
	let sourceCounts: Record<string, number> = $state({});
	let selectedDocTypes: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let yearOptions: FacetOption[] = $state([]);

	let docTypeOptions: FacetOption[] = $state([]);
	let oaOptions: FacetOption[] = $state([]);
	let apcOptions: FacetOption[] = $state([]);

	let pubsLoaded = $state(false);

	// Persons tab
	let persons: LabPerson[] = $state([]);
	let personsTotal = $state(0);
	let personsPage = $state(1);
	let personsPages = $state(1);
	let personsSort = $state('name');
	let personsSearch = $state('');
	let personsSearchTimer: ReturnType<typeof setTimeout>;
	let selectedRh: string[] = $state(['yes']);
	let selectedOrcid: string[] = $state([]);
	let selectedIdhal: string[] = $state([]);
	let rhOptions: FacetOption[] = $state([{ value: 'yes', text: 'Oui' }, { value: 'no', text: 'Non' }]);
	let orcidOptions: FacetOption[] = $state([{ value: 'yes', text: 'Avec' }, { value: 'no', text: 'Sans' }]);
	let idhalOptions: FacetOption[] = $state([{ value: 'yes', text: 'Avec' }, { value: 'no', text: 'Sans' }]);
	let orphanStats = $state({ total: 0 });
	let personsLoaded = $state(false);

	// Addresses tab
	let addresses: LabAddress[] = $state([]);
	let addrTotal = $state(0);
	let addrPage = $state(1);
	let addrPages = $state(1);
	let addrLoaded = $state(false);

	// Dashboard tab
	let dashboardLoaded = $state(false);
	let dashPubsByYear: { year: number; count: number }[] = $state([]);
	let dashOa: { open_access: number; closed: number; unknown: number; total: number } = $state({ open_access: 0, closed: 0, unknown: 0, total: 0 });
	let barCanvas: HTMLCanvasElement;
	let pieCanvas: HTMLCanvasElement;
	let barChart: Chart | null = null;
	let pieChart: Chart | null = null;

	const tutelles = $derived(parents.filter((p) => p.relation_type === 'est_tutelle_de'));
	const partenaires = $derived(parents.filter((p) => p.relation_type === 'est_partenaire_de'));

	function rorShortId(rorId: string): string {
		return rorId.replace('https://ror.org/', '');
	}

	function syncUrl() {
		const p = new URLSearchParams();
		if (activeTab !== 'publications') p.set('tab', activeTab);
		if (selectedYears.length) p.set('year', selectedYears.join(','));
		const sf = Object.entries(sourceStates).map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) p.set('source_filter', sf);
		if (selectedDocTypes.length) p.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) p.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) p.set('has_apc', selectedApc.join(','));
		if (pubSearch.trim()) p.set('search', pubSearch.trim());
		if (pubPage > 1) p.set('page', String(pubPage));
		if (personsSort !== 'name') p.set('psort', personsSort);
		const qs = p.toString();
		history.replaceState(history.state, '', `${base}/laboratories/${labId}` + (qs ? '?' + qs : ''));
	}

	function buildPubFilterParams(): URLSearchParams {
		const params = new URLSearchParams({ lab_id: labId });
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) params.set('has_apc', selectedApc.join(','));
		return params;
	}

	async function loadPubFacets() {
		const params = buildPubFilterParams();
		const data = await api<{
			years: { value: number; count: number }[];
			doc_types: { value: string; count: number }[];
			oa_statuses: { value: string; count: number }[];
			source_counts: Record<string, number>;
			apc: { value: string; text: string; count: number }[];
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
		sourceCounts = data.source_counts || {};
		if (data.apc) {
			apcOptions = data.apc.map(a => ({ value: a.value, text: a.text, count: a.count }));
		}
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
		syncUrl();
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
			syncUrl();
			loadPublications();
		}, 400);
	}

	function togglePersonsSort(col: string) {
		if (personsSort === col) personsSort = '-' + col;
		else if (personsSort === '-' + col) personsSort = col;
		else personsSort = col;
		personsPage = 1;
		loadPersons();
		syncUrl();
	}

	function sortIndicator(col: string): string {
		if (personsSort === col) return ' \u25B2';
		if (personsSort === '-' + col) return ' \u25BC';
		return '';
	}

	async function loadPersons() {
		const params = new URLSearchParams({
			page: String(personsPage),
			per_page: '50',
			sort: personsSort
		});
		if (personsSearch.trim()) params.set('search', personsSearch.trim());
		params.set('has_rh', selectedRh.length === 1 ? selectedRh[0] : 'all');
		if (selectedOrcid.length === 1) params.set('has_orcid', selectedOrcid[0]);
		if (selectedIdhal.length === 1) params.set('has_idhal', selectedIdhal[0]);
		const data = await api<PersonsResponse>(
			`/api/laboratories/${labId}/persons?${params}`
		);
		persons = data.persons;
		personsTotal = data.total_persons;
		personsPages = data.pages;
		personsPage = data.page;
		orphanStats = data.orphan_authorships;
		if (data.facets) {
			rhOptions = [
				{ value: 'yes', text: 'Oui', count: data.facets.rh.yes },
				{ value: 'no', text: 'Non', count: data.facets.rh.no }
			];
			orcidOptions = [
				{ value: 'yes', text: 'Avec', count: data.facets.orcid.yes },
				{ value: 'no', text: 'Sans', count: data.facets.orcid.no }
			];
			idhalOptions = [
				{ value: 'yes', text: 'Avec', count: data.facets.idhal.yes },
				{ value: 'no', text: 'Sans', count: data.facets.idhal.no }
			];
		}
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

	async function loadDashboard() {
		const data = await api<{
			pubs_by_year: { year: number; count: number }[];
			oa: { open_access: number; closed: number; unknown: number; total: number };
		}>(`/api/laboratories/${labId}/dashboard`);
		dashPubsByYear = data.pubs_by_year;
		dashOa = data.oa;
		dashboardLoaded = true;
		await tick();
		renderDashCharts();
	}

	function renderDashCharts() {
		if (barChart) barChart.destroy();
		if (pieChart) pieChart.destroy();

		const cs = getComputedStyle(document.documentElement);

		// Bar chart: publications par an
		if (barCanvas) {
			barChart = new Chart(barCanvas, {
				type: 'bar',
				data: {
					labels: dashPubsByYear.map(d => String(d.year)),
					datasets: [{
						label: 'Publications',
						data: dashPubsByYear.map(d => d.count),
						backgroundColor: cs.getPropertyValue('--accent')?.trim() || '#3b6b9e',
						borderRadius: 3,
					}]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: { legend: { display: false } },
					scales: {
						y: { beginAtZero: true, ticks: { precision: 0 } },
						x: { grid: { display: false } }
					}
				}
			});
		}

		// Pie chart: OA
		if (pieCanvas && dashOa.total > 0) {
			pieChart = new Chart(pieCanvas, {
				type: 'doughnut',
				data: {
					labels: ['Open Access', 'Closed', 'Indéterminé'],
					datasets: [{
						data: [dashOa.open_access, dashOa.closed, dashOa.unknown],
						backgroundColor: ['#2a7d4f', '#c0392b', '#ccc'],
					}]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { position: 'bottom' },
					}
				}
			});
		}
	}

	function switchTab(tab: Tab) {
		// Update tab via goto (triggers $derived activeTab update)
		const url = new URL($page.url);
		if (tab === 'dashboard') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, noScroll: true }).then(() => syncUrl());
		if (tab === 'dashboard') loadDashboard();
		if (tab === 'publications' && !pubsLoaded) { loadPubFacets(); loadPublications(); }
		if (tab === 'persons' && !personsLoaded) loadPersons();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	onMount(async () => {
		canGoBack = (window.navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));

		// Restore filters from URL
		const urlParams = $page.url.searchParams;
		if (urlParams.get('year')) selectedYears = urlParams.get('year')!.split(',');
		if (urlParams.get('doc_type')) selectedDocTypes = urlParams.get('doc_type')!.split(',');
		if (urlParams.get('oa_status')) selectedOa = urlParams.get('oa_status')!.split(',');
		if (urlParams.get('has_apc')) selectedApc = urlParams.get('has_apc')!.split(',');
		if (urlParams.get('source_filter')) {
			const states: Record<string, string> = {};
			for (const v of urlParams.get('source_filter')!.split(',')) {
				const m = v.match(/^(\w+)_(yes|no)$/);
				if (m) states[m[1]] = m[2];
			}
			sourceStates = states;
		}
		if (urlParams.get('search')) pubSearch = urlParams.get('search')!;
		if (urlParams.get('page')) pubPage = Number(urlParams.get('page')) || 1;
		if (urlParams.get('psort')) personsSort = urlParams.get('psort')!;

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
		if (activeTab === 'dashboard') {
			loadDashboard();
		} else if (activeTab === 'publications') {
			loadPubFacets();
			loadPublications();
		} else if (activeTab === 'persons') {
			loadPersons();
		} else if (activeTab === 'addresses') {
			loadAddresses();
		}
	});
</script>

<svelte:head>
	<title>{lab ? (lab.acronym || lab.name) : 'Laboratoire'} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
<!-- svelte-ignore a11y_invalid_attribute -->
<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

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
		<button class="tab" class:active={activeTab === 'dashboard'} onclick={() => switchTab('dashboard')}>
			Dashboard
		</button>
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

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if !dashboardLoaded}
				<div class="loading">Chargement...</div>
			{:else}
				<div class="dash-grid">
					<div class="dash-card">
						<h3>Publications par année</h3>
						<div class="chart-wrap">
							<canvas bind:this={barCanvas}></canvas>
						</div>
					</div>
					<div class="dash-card">
						<h3>Open Access</h3>
						<div class="chart-wrap">
							<canvas bind:this={pieCanvas}></canvas>
						</div>
						{#if dashOa.total > 0}
							<div class="oa-summary">
								{Math.round(dashOa.open_access / dashOa.total * 100)} % Open Access
								({dashOa.open_access.toLocaleString('fr-FR')} / {dashOa.total.toLocaleString('fr-FR')})
							</div>
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<div class="toolbar">
				<input type="text" placeholder="Rechercher par titre..." bind:value={pubSearch} oninput={onSearchInput} />
				<FacetDropdown label="Années" options={yearOptions} bind:selected={selectedYears} onchange={onFilterChange} />
				<FacetDropdown label="Types" options={docTypeOptions} bind:selected={selectedDocTypes} onchange={onFilterChange} />
				<FacetDropdown label="Voies OA" options={oaOptions} bind:selected={selectedOa} onchange={onFilterChange} />
				<FacetDropdown label="APC" options={apcOptions} bind:selected={selectedApc} onchange={onFilterChange} tooltip="Pas d'info après 2024<br>Sans APC = ou APC non documentés" />
				<SourceFilterToggle bind:states={sourceStates} counts={sourceCounts} onchange={onFilterChange} />
				<span class="count">{pubTotal} publication{pubTotal > 1 ? 's' : ''}</span>
				<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
			</div>
			<table class="pub-table">
				<thead>
					<tr>
						<th>Titre</th>
						<th>Revue</th>
						<th style="width:80px">Type</th>
						<th style="width:40px">An.</th>
						<th style="width:60px">APC</th>
						<th style="width:50px">OA</th>
						<th style="width:80px">Liens</th>
					</tr>
				</thead>
				<tbody>
					{#if publications.length === 0}
						<tr><td colspan="7" class="no-results">Aucune publication</td></tr>
					{:else}
						{#each publications as p (p.id)}
							<tr>
								<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
								<td class="journal-cell">{p.journal || ''}</td>
								<td>
									<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
								</td>
								<td>{p.pub_year || ''}</td>
								<td class="apc-cell">
									{#if p.apc}
										{@const thisLabApc = p.apc.filter(a => a.lab_id === lab?.id)}
										{@const otherApc = p.apc.filter(a => a.lab_id !== lab?.id)}
										{#if thisLabApc.length > 0}
											<span class="apc-tag" title={thisLabApc.map(a => `${a.amount?.toLocaleString('fr-FR')} €`).join('\n')}>
												{Math.round(thisLabApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
											</span>
										{:else if otherApc.length > 0}
											<span class="apc-tag apc-other" title={otherApc.map(a => `sur budget ${a.lab_acronym || a.institution || '?'}`).join('\n')}>
												{Math.round(otherApc.reduce((s, a) => s + (a.amount || 0), 0)).toLocaleString('fr-FR')} €
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
											<svg viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
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
			<Pagination page={pubPage} pages={pubPages} onchange={(p) => { pubPage = p; syncUrl(); loadPublications(); window.scrollTo(0, 0); }} />
		</div>
	{/if}

	<!-- Tab: Personnes -->
	{#if activeTab === 'persons'}
		<div class="tab-content">
			{#if orphanStats.total > 0}
				<a href="{base}/admin/authorships?lab={labId}&linked=no" class="orphan-banner">
					{orphanStats.total} authorship{orphanStats.total > 1 ? 's' : ''} non relié{orphanStats.total > 1 ? 'es' : 'e'} à une personne
				</a>
			{/if}
			<div class="toolbar">
				<input type="text" placeholder="Rechercher..." bind:value={personsSearch} oninput={() => { clearTimeout(personsSearchTimer); personsSearchTimer = setTimeout(() => { personsPage = 1; loadPersons(); }, 300); }} />
				<FacetDropdown label="Base RH" options={rhOptions} bind:selected={selectedRh} onchange={() => { personsPage = 1; loadPersons(); }} />
				<FacetDropdown label="ORCID" options={orcidOptions} bind:selected={selectedOrcid} onchange={() => { personsPage = 1; loadPersons(); }} />
				<FacetDropdown label="idHAL" options={idhalOptions} bind:selected={selectedIdhal} onchange={() => { personsPage = 1; loadPersons(); }} />
				<span class="count">{personsTotal} personne{personsTotal > 1 ? 's' : ''}</span>
			</div>
			<table>
				<thead>
					<tr>
						<th class="sortable" onclick={() => togglePersonsSort('name')}>Nom{sortIndicator('name')}</th>
						<th>ORCID</th>
						<th class="sortable" onclick={() => togglePersonsSort('role')}>Fonction{sortIndicator('role')}</th>
						<th class="sortable" onclick={() => togglePersonsSort('dept')}>Département{sortIndicator('dept')}</th>
						<th class="sortable" style="width:80px" onclick={() => togglePersonsSort('pubs')}>Publications{sortIndicator('pubs')}</th>
					</tr>
				</thead>
				<tbody>
					{#if persons.length === 0}
						<tr><td colspan="5" class="no-results">Aucune personne trouvée</td></tr>
					{:else}
						{#each persons as p (p.id)}
							<tr>
								<td>
									<a href="{base}/persons/{p.id}" class="person-link">
										{p.first_name} <span class="person-last">{p.last_name}</span>
									</a>
									{#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
								</td>
								<td>{#each p.orcids || [] as oid}<a href="https://orcid.org/{oid.value}" target="_blank" rel="noopener" class="id-badge" class:id-confirmed={oid.confirmed}>{oid.value}</a>{/each}</td>
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
		font-size: 0.95rem;
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
		font-size: 1.3rem;
		font-weight: 600;
		margin: 0 0 10px;
	}
	.lab-acronym {
		font-size: 1.05rem;
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
		font-size: 0.95rem;
	}
	.meta-label {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.3px;
	}
	.tutelle-tag, .partner-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 0.8rem;
		white-space: nowrap;
	}
	.tutelle-tag { background: #e8f0f8; color: var(--accent); }
	.partner-tag { background: #f0efec; color: var(--muted); }
	.id-badge {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 0.8rem;
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
		font-size: 0.95rem;
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
		font-size: 0.8rem;
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
		font-size: 0.95rem;
		width: 220px;
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

	/* Dashboard */
	.dash-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}
	.dash-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 16px;
	}
	.dash-card h3 {
		font-size: 0.95rem;
		font-weight: 600;
		margin: 0 0 12px;
	}
	.chart-wrap {
		position: relative;
		height: 280px;
	}
	.oa-summary {
		text-align: center;
		font-size: 0.9rem;
		color: var(--muted);
		margin-top: 8px;
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
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.tab-content thead th.sortable {
		cursor: pointer;
		user-select: none;
	}
	.tab-content thead th.sortable:hover {
		color: var(--accent);
	}
	.tab-content tbody tr { border-bottom: 1px solid #f0efec; }
	.tab-content tbody tr:last-child { border-bottom: none; }
	.tab-content tbody tr:hover { background: #fafaf8; }
	.tab-content td {
		padding: 7px 10px;
		font-size: 0.95rem;
		vertical-align: top;
	}

	/* Publications tab */
	.pub-title {
		font-weight: 500; color: var(--text);
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
	.apc-cell { text-align: right; white-space: nowrap; }
	.apc-tag {
		display: inline-block; font-size: 0.75rem; padding: 1px 5px;
		border-radius: 3px; background: #e8f5e9; color: #2e7d32;
		font-weight: 500; cursor: default;
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
		font-size: 0.7rem;
		font-weight: 700;
		margin-left: 4px;
		vertical-align: middle;
		line-height: 1;
	}
	.muted-cell { font-size: 0.85rem; color: var(--muted); }
	.id-badge {
		display: inline-block; padding: 2px 7px; background: #e8f0f8;
		border-radius: 3px; font-size: 0.8rem; color: var(--accent);
		text-decoration: none; white-space: nowrap;
	}
	.id-badge:hover { background: #d4e4f3; text-decoration: none; }
	.id-confirmed { background: #e6f4ec; color: #2a7d4f; }
	.id-confirmed:hover { background: #d0eadb; }
	.orphan-banner {
		display: block;
		background: #fef3e0;
		border: 1px solid #f0dca0;
		border-radius: 5px;
		padding: 8px 14px;
		margin-bottom: 12px;
		font-size: 0.95rem;
		color: #8a6d1b;
		text-decoration: none;
	}
	.orphan-banner:hover {
		background: #fdecc8;
	}
	.orphan-detail {
		font-size: 0.85rem;
		color: #a08530;
	}

	/* Addresses tab */
	.addr-cell {
		font-size: 0.85rem;
		color: var(--muted);
		word-break: break-all;
	}
	.status-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 0.8rem;
		font-weight: 500;
	}
	.status-tag.confirmed { background: #e6f4ec; color: #2a7d4f; }
	.status-tag.pending { background: #f0efec; color: var(--muted); }

	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
