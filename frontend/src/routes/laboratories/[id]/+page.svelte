<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { sanitizeTitle, halDocUrl, scanrPubUrl } from '$lib/utils';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	Chart.register(...registerables, ChartDataLabels);
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import TabNav from '$lib/components/TabNav.svelte';
	import { docTypeLabelsMap, oaLabelsMap, typeLabels } from '$lib/labels';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';

	const labId = $derived($page.params.id);
	let canGoBack = $state(false);

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
		scanr_id: string | null;
		wos_id: string | null;
		labs: string | null;
		apc: { amount: number; institution: string | null; lab_id: number | null; lab_acronym: string | null; budget_structure_id: number | null }[] | null;
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
		facets?: {
			rh: { yes: number; no: number };
			orcid: { yes: number; no: number };
			idhal: { yes: number; no: number };
		};
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

	const validTabs = ['dashboard', 'publications', 'persons', 'addresses'];
	const activeTab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab');
			return t && validTabs.includes(t) ? t : 'dashboard';
		})()
	);

	// --- Publication filters ---
	let pubSearch = $state('');
	let selectedYears: string[] = $state([]);
	let sourceStates: Record<string, string> = $state({});
	let selectedDocTypes: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedApc: string[] = $state([]);
	let selectedCountries: string[] = $state([]);
	let pubSort = $state('year_desc');

	function togglePubSortYear() {
		pubSort = pubSort === 'year_desc' ? 'year_asc' : 'year_desc';
		pubs.page = 1; syncUrl(); pubs.load();
	}
	function togglePubSortTitle() {
		pubSort = pubSort === 'title' ? 'title_desc' : 'title';
		pubs.page = 1; syncUrl(); pubs.load();
	}

	// --- Persons tab (manual state: API returns total_persons, not total, + inline facets) ---
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
	let dashCollab: { total_articles: number; international: number; domestic: number } = $state({ total_articles: 0, international: 0, domestic: 0 });
	let dashTopCountries: { code: string; name: string; count: number }[] = $state([]);
	let barCanvas: HTMLCanvasElement;
	let pieCanvas: HTMLCanvasElement;
	let collabCanvas: HTMLCanvasElement;
	let countriesCanvas: HTMLCanvasElement;
	let barChart: Chart | null = null;
	let pieChart: Chart | null = null;
	let collabChart: Chart | null = null;
	let countriesChart: Chart | null = null;

	const tutelles = $derived(parents.filter((p) => p.relation_type === 'est_tutelle_de'));
	const partenaires = $derived(parents.filter((p) => p.relation_type === 'est_partenaire_de'));

	function rorShortId(rorId: string): string {
		return rorId.replace('https://ror.org/', '');
	}

	// --- Shared filter params builder (bridge between filter state and composables) ---
	function buildPubFilterParams(): URLSearchParams {
		const params = new URLSearchParams({ lab_id: labId });
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedApc.length) params.set('has_apc', selectedApc.join(','));
		if (selectedCountries.length) params.set('country', selectedCountries.join(','));
		return params;
	}

	// --- Composables: Publications ---
	const pubs = usePaginatedFetch<Publication>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		perPage: 50,
		apiKey: 'lab-pubs',
		buildParams() {
			const params = buildPubFilterParams();
			params.set('sort', pubSort);
			const q = pubSearch.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: '/api/publications/facets',
		apiKey: 'lab-pub-facets',
		buildParams: buildPubFilterParams,
		sourceCountsKey: 'source_counts',
		facets: {
			years:     { type: 'simple',      apiKey: 'years' },
			docTypes:  { type: 'label_map',   apiKey: 'doc_types',   labels: docTypeLabelsMap },
			oa:        { type: 'label_map',   apiKey: 'oa_statuses', labels: oaLabelsMap },
			apc:       { type: 'passthrough', apiKey: 'apc' },
			countries: { type: 'passthrough', apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.text} (${c.value.toUpperCase()})`, count: c.count }) },
		},
	});

	const url = useUrlFilters({
		basePath: `/laboratories/${labId}`,
		filters: {
			tab:              { type: 'single',        urlKey: 'tab', defaultValue: 'publications' },
			selectedYears:    { type: 'string_array',  urlKey: 'year' },
			sourceStates:     { type: 'source_states', urlKey: 'source_filter' },
			selectedDocTypes: { type: 'string_array',  urlKey: 'doc_type' },
			selectedOa:       { type: 'string_array',  urlKey: 'oa_status' },
			selectedApc:      { type: 'string_array',  urlKey: 'has_apc' },
			selectedCountries:{ type: 'string_array',  urlKey: 'country' },
			pubSearch:        { type: 'single',        urlKey: 'search' },
			pubSort:          { type: 'single',        urlKey: 'sort', defaultValue: 'year_desc' },
			currentPage:      { type: 'page',          urlKey: 'page' },
			personsSort:      { type: 'single',        urlKey: 'psort', defaultValue: 'name' },
			hasRh:            { type: 'single',        urlKey: 'has_rh', defaultValue: 'yes' },
			hasOrcid:         { type: 'single',        urlKey: 'has_orcid' },
			hasIdhal:         { type: 'single',        urlKey: 'has_idhal' },
			personsPage:      { type: 'page',          urlKey: 'ppage' },
			addrPage:         { type: 'page',          urlKey: 'apage' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		url.syncUrl(() => ({
			tab: activeTab,
			selectedYears, sourceStates, selectedDocTypes,
			selectedOa, selectedApc, selectedCountries, pubSearch, pubSort,
			currentPage: pubs.page,
			personsSort,
			hasRh: selectedRh.length === 1 ? selectedRh[0] : 'all',
			hasOrcid: selectedOrcid.length === 1 ? selectedOrcid[0] : undefined,
			hasIdhal: selectedIdhal.length === 1 ? selectedIdhal[0] : undefined,
			personsPage,
			addrPage,
		}));
	}

	function onFilterChange() {
		pubs.page = 1;
		syncUrl();
		pubs.load();
		facets.load();
	}

	function exportCsvUrl(): string {
		const params = buildPubFilterParams();
		params.set('sort', 'year_desc');
		const q = pubSearch.trim();
		if (q) params.set('search', q);
		return `${base}/api/publications/export.csv?${params}`;
	}

	const onSearchInput = url.debouncedSearch(() => {
		pubs.page = 1;
		syncUrl();
		pubs.load();
	});

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
			`/api/laboratories/${labId}/persons?${params}`, { key: 'lab-persons' }
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
			`/api/laboratories/${labId}/addresses?${params}`, { key: 'lab-addresses' }
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
			collab: { total_articles: number; international: number; domestic: number };
			top_countries: { code: string; name: string; count: number }[];
		}>(`/api/laboratories/${labId}/dashboard`, { key: 'lab-dashboard' });
		dashPubsByYear = data.pubs_by_year;
		dashOa = data.oa;
		dashCollab = data.collab;
		dashTopCountries = data.top_countries;
		dashboardLoaded = true;
		await tick();
		renderDashCharts();
	}

	function renderDashCharts() {
		if (barChart) barChart.destroy();
		if (pieChart) pieChart.destroy();
		if (collabChart) collabChart.destroy();
		if (countriesChart) countriesChart.destroy();

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
					plugins: {
						legend: { display: false },
						datalabels: { color: '#fff', font: { weight: 'bold', size: 12 } }
					},
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
						datalabels: {
							color: '#fff',
							font: { weight: 'bold', size: 13 },
							formatter: (value: number, ctx: any) => {
								const total = ctx.dataset.data.reduce((a: number, b: number) => a + b, 0);
								const pct = total > 0 ? Math.round(value / total * 100) : 0;
								return pct > 3 ? `${pct}%` : '';
							}
						}
					}
				}
			});
		}

		// Doughnut: collaborations internationales (articles)
		if (collabCanvas && dashCollab.total_articles > 0) {
			collabChart = new Chart(collabCanvas, {
				type: 'doughnut',
				data: {
					labels: ['International', 'Domestique'],
					datasets: [{
						data: [dashCollab.international, dashCollab.domestic],
						backgroundColor: ['#3b6b9e', '#e0e0e0'],
					}]
				},
				options: {
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { position: 'bottom' },
						datalabels: {
							color: '#fff',
							font: { weight: 'bold', size: 13 },
							formatter: (value: number, ctx: any) => {
								const total = ctx.dataset.data.reduce((a: number, b: number) => a + b, 0);
								const pct = total > 0 ? Math.round(value / total * 100) : 0;
								return pct > 3 ? `${pct}%` : '';
							}
						}
					}
				}
			});
		}

		// Bar: top 5 pays (hors FR)
		if (countriesCanvas && dashTopCountries.length > 0) {
			countriesChart = new Chart(countriesCanvas, {
				type: 'bar',
				data: {
					labels: dashTopCountries.map(c => `${c.name}`),
					datasets: [{
						label: 'Articles',
						data: dashTopCountries.map(c => c.count),
						backgroundColor: '#e8a838',
						borderRadius: 3,
					}]
				},
				options: {
					indexAxis: 'y',
					responsive: true,
					maintainAspectRatio: false,
					plugins: {
						legend: { display: false },
						datalabels: { color: '#fff', font: { weight: 'bold', size: 12 } }
					},
					scales: {
						x: { beginAtZero: true, ticks: { precision: 0 } },
						y: { grid: { display: false } }
					}
				}
			});
		}
	}

	function onTabSwitch(tab: string) {
		if (tab === 'dashboard') loadDashboard();
		if (tab === 'publications' && !pubs.loaded) { facets.load(); pubs.load(); }
		if (tab === 'persons' && !personsLoaded) loadPersons();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	onMount(async () => {
		canGoBack = (window.navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));

		// Restore filters from URL
		const restored = url.restoreFromUrl($page.url.searchParams);
		if (restored.selectedYears) selectedYears = restored.selectedYears as string[];
		if (restored.sourceStates) sourceStates = restored.sourceStates as Record<string, string>;
		if (restored.selectedDocTypes) selectedDocTypes = restored.selectedDocTypes as string[];
		if (restored.selectedOa) selectedOa = restored.selectedOa as string[];
		if (restored.selectedApc) selectedApc = restored.selectedApc as string[];
		if (restored.selectedCountries) selectedCountries = restored.selectedCountries as string[];
		if (restored.pubSearch) pubSearch = restored.pubSearch as string;
		if (restored.pubSort) pubSort = restored.pubSort as string;
		if (restored.currentPage) pubs.page = restored.currentPage as number;
		if (restored.personsSort) personsSort = restored.personsSort as string;
		if (restored.hasRh != null) {
			const rh = restored.hasRh as string;
			selectedRh = rh === 'all' ? [] : [rh];
		}
		if (restored.hasOrcid != null) {
			const o = restored.hasOrcid as string;
			selectedOrcid = o === 'all' ? [] : [o];
		}
		if (restored.hasIdhal != null) {
			const h = restored.hasIdhal as string;
			selectedIdhal = h === 'all' ? [] : [h];
		}
		if (restored.personsPage) personsPage = restored.personsPage as number;
		if (restored.addrPage) addrPage = restored.addrPage as number;

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
			facets.load();
			pubs.load();
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
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard', showCount: false },
			{ id: 'publications', label: 'Publications', count: pubs.total },
			{ id: 'persons', label: 'Personnes', count: personsLoaded ? personsTotal : undefined },
			{ id: 'addresses', label: 'Adresses', count: addrLoaded ? addrTotal : undefined },
		]}
		onswitch={onTabSwitch}
		afterNavigate={syncUrl}
	/>

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
					<div class="dash-card">
						<h3>Collaborations internationales (articles)</h3>
						<div class="chart-wrap">
							<canvas bind:this={collabCanvas}></canvas>
						</div>
						{#if dashCollab.total_articles > 0}
							<div class="oa-summary">
								{Math.round(dashCollab.international / dashCollab.total_articles * 100)} % international
								({dashCollab.international.toLocaleString('fr-FR')} / {dashCollab.total_articles.toLocaleString('fr-FR')} articles)
							</div>
						{/if}
					</div>
					<div class="dash-card">
						<h3>Top 5 pays partenaires (articles)</h3>
						<div class="chart-wrap">
							<canvas bind:this={countriesCanvas}></canvas>
						</div>
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<div class="toolbar toolbar-card">
				<input type="text" placeholder="Rechercher par titre..." bind:value={pubSearch} oninput={onSearchInput} />
				<FacetDropdown label="Années" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />
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
						<th class="sortable" class:active={pubSort === 'title' || pubSort === 'title_desc'} onclick={togglePubSortTitle}>Titre {pubSort === 'title' ? '↑' : pubSort === 'title_desc' ? '↓' : ''}</th>
						<th>Revue</th>
						<th style="width:80px">Type</th>
						<th style="width:40px" class="sortable" class:active={pubSort === 'year_desc' || pubSort === 'year_asc'} onclick={togglePubSortYear}>An. {pubSort === 'year_asc' ? '↑' : '↓'}</th>
						<th style="width:60px">APC</th>
						<th style="width:50px">OA</th>
						<th style="width:80px">Liens</th>
					</tr>
				</thead>
				<tbody>
					{#if pubs.items.length === 0}
						<tr><td colspan="7" class="no-results">Aucune publication</td></tr>
					{:else}
						{#each pubs.items as p (p.id)}
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
			<Pagination page={pubs.page} pages={pubs.pages} onchange={(p) => { pubs.goToPage(p); syncUrl(); }} />
		</div>
	{/if}

	<!-- Tab: Personnes -->
	{#if activeTab === 'persons'}
		<div class="tab-content">
			{#if orphanStats.total > 0}
				<div class="orphan-banner">
					{orphanStats.total} authorship{orphanStats.total > 1 ? 's' : ''} non relié{orphanStats.total > 1 ? 'es' : 'e'} à une personne
				</div>
			{/if}
			<div class="toolbar toolbar-card">
				<input type="text" placeholder="Rechercher..." bind:value={personsSearch} oninput={() => { clearTimeout(personsSearchTimer); personsSearchTimer = setTimeout(() => { personsPage = 1; loadPersons(); }, 300); }} />
				<FacetDropdown label="Base RH" options={rhOptions} bind:selected={selectedRh} onchange={() => { personsPage = 1; syncUrl(); loadPersons(); }} />
				<FacetDropdown label="ORCID" options={orcidOptions} bind:selected={selectedOrcid} onchange={() => { personsPage = 1; syncUrl(); loadPersons(); }} />
				<FacetDropdown label="idHAL" options={idhalOptions} bind:selected={selectedIdhal} onchange={() => { personsPage = 1; syncUrl(); loadPersons(); }} />
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
			<Pagination page={personsPage} pages={personsPages} onchange={(p) => { personsPage = p; syncUrl(); loadPersons(); }} />
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
			<Pagination page={addrPage} pages={addrPages} onchange={(p) => { addrPage = p; syncUrl(); loadAddresses(); }} />
		</div>
	{/if}
{/if}

<style>
	/* Header */
	.lab-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
		margin-bottom: 0;
	}
	.lab-name { font-size: 1.3rem; font-weight: 600; margin: 0 0 10px; }
	.lab-acronym { font-size: 1.05rem; color: var(--muted); font-weight: 400; }
	.lab-meta { display: flex; flex-direction: column; gap: 6px; }
	.meta-row {
		display: flex; align-items: center; gap: 6px;
		flex-wrap: wrap; font-size: 0.95rem;
	}
	.meta-label {
		font-size: 0.8rem; font-weight: 600; color: var(--muted);
		text-transform: uppercase; letter-spacing: 0.3px;
	}
	.tutelle-tag { background: #e8f0f8; color: var(--accent); }
	.partner-tag { background: #f0efec; color: var(--muted); }
	.id-badge { margin-right: 8px; }

	/* Toolbar */
	.toolbar input[type='text'] { width: 220px; }

	/* Dashboard */
	.dash-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
	.dash-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 16px;
	}
	.dash-card h3 { font-size: 0.95rem; font-weight: 600; margin: 0 0 12px; }
	.chart-wrap { position: relative; height: 280px; }
	.oa-summary { text-align: center; font-size: 0.9rem; color: var(--muted); margin-top: 8px; }

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
	.tab-content thead th.sortable { cursor: pointer; user-select: none; }
	.tab-content thead th.sortable:hover { color: var(--accent); }
	.tab-content thead th.sortable.active { color: var(--accent); }
	.tab-content tbody tr { border-bottom: 1px solid #f0efec; }
	.tab-content tbody tr:last-child { border-bottom: none; }
	.tab-content tbody tr:hover { background: #fafaf8; }
	.tab-content td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }

	/* Persons tab */
	.person-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.person-link:hover { text-decoration: underline; }
	.person-last { font-weight: 600; }
	.muted-cell { font-size: 0.85rem; color: var(--muted); }
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
	.orphan-banner:hover { background: #fdecc8; }
	.orphan-detail { font-size: 0.85rem; color: #a08530; }

	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
	.status-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 0.8rem;
		font-weight: 500;
	}
	.status-tag.confirmed { background: #e6f4ec; color: #2a7d4f; }
	.status-tag.pending { background: #f0efec; color: var(--muted); }
</style>
