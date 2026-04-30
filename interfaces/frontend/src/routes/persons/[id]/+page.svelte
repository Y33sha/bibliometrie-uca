<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api, auth, authorships } from '$lib/api';
	import { titleCase, formatDate, sanitizeTitle, halDocUrl, scanrPubUrl } from '$lib/utils';
	import { typeLabels, docTypeLabelsMap, oaLabelsMap } from '$lib/labels';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	Chart.register(...registerables, ChartDataLabels);
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { useFacets } from '$lib/composables/useFacets.svelte';
	import { useColumnVisibility } from '$lib/composables/useColumnVisibility.svelte';
	import ColumnMenu from '$lib/components/ColumnMenu.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import IdentifiersCell from '$lib/components/IdentifiersCell.svelte';
	import PresenceFilterToggle from '$lib/components/PresenceFilterToggle.svelte';
	import { SOURCE_ITEMS } from '$lib/filterItems';
	import SubjectsCloud from '$lib/components/SubjectsCloud.svelte';
	import TabNav from '$lib/components/TabNav.svelte';
	import type { components } from '$lib/api/schema';

	const personId = $derived($page.params.id);
	let canGoBack = $state(false);

	// --- Types ---
	type Person = components['schemas']['PersonProfileCore'];
	type Identifier = components['schemas']['PersonIdentifierOut'];
	type Author = components['schemas']['PersonProfileAuthor'];
	type ProfileResponse = components['schemas']['PersonProfileResponse'];
	type Address = components['schemas']['PersonAddressOut'];
	type ThesisEntry = components['schemas']['PersonThesis'];
	type ThesisSection = components['schemas']['PersonThesesSection'];
	type ThesisStructInfo = components['schemas']['StructureRef'];
	type ThesesResponse = components['schemas']['PersonThesesResponse'];
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
		lab_items: { id: number; label: string }[] | null;
		apc: { amount: number; institution: string | null; lab_id: number | null; lab_acronym: string | null; budget_structure_id: number | null }[] | null;
		is_corresponding: boolean | null;
		authorship_id: number | null;
	}

	// --- State ---
	let profile = $state<Person | null>(null);
	let identifiers = $state<Identifier[]>([]);
	let authors = $state<Author[]>([]);
	let thesesCount = $state(0);
	let error = $state(false);
	let isAdmin = $state(false);

	const activeTab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab');
			return t === 'publications' || t === 'theses' || t === 'addresses' ? t : 'dashboard';
		})()
	);

	// --- Column visibility ---
	const cv = useColumnVisibility([
		{ key: 'type',    label: 'Type' },
		{ key: 'year',    label: 'Année' },
		{ key: 'title',   label: 'Titre',    fixed: true },
		{ key: 'journal', label: 'Revue' },
		{ key: 'labs',    label: 'Labo(s)' },
		{ key: 'corr',    label: 'Corresp.' },
		{ key: 'apc',     label: 'APC' },
		{ key: 'oa',      label: 'OA' },
		{ key: 'oa_path', label: 'Voie OA' },
		{ key: 'links',   label: 'Liens',    fixed: true },
	], ['apc', 'oa_path']);
	const col = cv.col;

	// Facet filter selections
	let selectedYears: string[] = $state([]);
	let selectedDocTypes: string[] = $state([]);
	let selectedAccess: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedCorr: string[] = $state([]);
	let selectedPerimeter: string[] = $state([]);
	let selectedCountries: string[] = $state([]);
	let sourceStates = $state<Record<string, 'all' | 'yes' | 'no'>>({});
	let currentSort = $state('year_desc');

	function toggleSortYear() {
		currentSort = currentSort === 'year_desc' ? 'year_asc' : 'year_desc';
		pubs.load(); facets.load();
	}
	function toggleSortTitle() {
		currentSort = currentSort === 'title' ? 'title_desc' : 'title';
		pubs.load(); facets.load();
	}

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('person_id', personId ?? '');
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedAccess.length) params.set('access', selectedAccess.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedCorr.length) params.set('is_corresponding', selectedCorr.join(','));
		if (selectedPerimeter.length) params.set('in_perimeter', selectedPerimeter.join(','));
		if (selectedCountries.length) params.set('country', selectedCountries.join(','));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		return params;
	}

	// Publications (paginated)
	const pubs = usePaginatedFetch<Publication>({
		endpoint: '/api/publications',
		itemsKey: 'publications',
		perPage: 50,
		apiKey: 'person-detail-pubs',
		buildParams: () => {
			const params = buildFilterParams();
			params.set('sort', currentSort);
			return params;
		},
	});

	// Facets
	const facets = useFacets<'years' | 'docTypes' | 'access' | 'oa' | 'corresponding' | 'perimeter' | 'countries'>({
		endpoint: '/api/publications/facets',
		apiKey: 'person-detail-facets',
		buildParams: () => buildFilterParams(),
		facets: {
			years: { type: 'simple', apiKey: 'years' },
			docTypes: { type: 'label_map', apiKey: 'doc_types', labels: docTypeLabelsMap },
			access: { type: 'passthrough', apiKey: 'access' },
			oa: { type: 'label_map', apiKey: 'oa_statuses', labels: oaLabelsMap },
			corresponding: { type: 'boolean', apiKey: 'corresponding', yesLabel: 'Oui', noLabel: 'Non' },
			perimeter: { type: 'passthrough', apiKey: 'in_perimeter' },
			countries: {
				type: 'passthrough',
				apiKey: 'countries',
				transform: (c) => ({ value: c.value, text: `${c.text} (${c.value.toUpperCase()})`, count: c.count }),
			},
		},
		sourceCountsKey: 'source_counts',
	});

	function onFilterChange() {
		pubs.page = 1;
		pubs.load();
		facets.load();
	}

	// Theses tab
	let thesesSections: ThesisSection[] = $state([]);
	let thesesTotal = $state(0);
	let thesesStructures = $state<Record<string, ThesisStructInfo>>({});
	let thesesLoaded = $state(false);

	// Addresses tab
	let addresses: Address[] = $state([]);
	let addrTotal = $state(0);
	let addrPage = $state(1);
	let addrPages = $state(1);
	let addrLoaded = $state(false);

	// Dashboard tab
	type DashboardResponse = components['schemas']['PersonDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	let dashboardLoaded = $state(false);
	let dashPubsByYear: { year: number; count: number }[] = $state([]);
	let dashOa = $state({ open_access: 0, closed: 0, unknown: 0, total: 0 });
	let dashSubjects: SubjectFrequency[] = $state([]);
	let barCanvas = $state<HTMLCanvasElement | undefined>();
	let pieCanvas = $state<HTMLCanvasElement | undefined>();
	let barChart: Chart | null = null;
	let pieChart: Chart | null = null;

	const displayName = $derived(
		profile
			? `${titleCase(profile.first_name)} ${titleCase(profile.last_name)}`
			: ''
	);

	const allOrcids = $derived(() => {
		const map = new Map<string, boolean>();
		identifiers.filter((i) => i.id_type === 'orcid' && i.status !== 'rejected').forEach((i) => {
			map.set(i.id_value, map.get(i.id_value) || i.status === 'confirmed');
		});
		return Array.from(map, ([value, confirmed]) => ({ value, confirmed }));
	});

	const allIdhals = $derived(() => {
		// Aligné sur ORCID / IdRef : seule person_identifiers fait foi.
		// On ne fusionne plus les idhal des entités auteurs HAL (qui peuvent
		// contenir des valeurs polluées — typiquement un hal_person_id
		// numérique mal interprété en idhal).
		const map = new Map<string, boolean>();
		identifiers.filter((i) => i.id_type === 'idhal' && i.status !== 'rejected').forEach((i) => {
			map.set(i.id_value, map.get(i.id_value) || i.status === 'confirmed');
		});
		return Array.from(map, ([value, confirmed]) => ({ value, confirmed }));
	});

	const allIdrefs = $derived(() => {
		const map = new Map<string, boolean>();
		identifiers.filter((i) => i.id_type === 'idref' && i.status !== 'rejected').forEach((i) => {
			map.set(i.id_value, map.get(i.id_value) || i.status === 'confirmed');
		});
		return Array.from(map, ([value, confirmed]) => ({ value, confirmed }));
	});

	async function loadTheses() {
		const res = await api<ThesesResponse>(
			`/api/persons/${personId}/theses`, { key: 'person-detail-theses' }
		);
		thesesSections = res.sections;
		thesesTotal = res.total;
		thesesStructures = res.structures;
		thesesLoaded = true;
	}

	async function loadAddresses() {
		const params = new URLSearchParams({
			page: String(addrPage),
			per_page: '50'
		});
		const data = await api<{
			total: number; page: number; pages: number; addresses: Address[];
		}>(`/api/persons/${personId}/addresses?${params}`, { key: 'person-detail-addresses' });
		addresses = data.addresses;
		addrTotal = data.total;
		addrPages = data.pages;
		addrPage = data.page;
		addrLoaded = true;
	}

	async function loadDashboard() {
		const [data, subjects] = await Promise.all([
			api<DashboardResponse>(`/api/persons/${personId}/dashboard`, { key: 'person-detail-dashboard' }),
			api<SubjectFrequency[]>(`/api/persons/${personId}/subjects?limit=30`, { key: 'person-detail-subjects' }),
		]);
		dashPubsByYear = data.pubs_by_year;
		dashOa = data.oa;
		dashSubjects = subjects;
		dashboardLoaded = true;
		// Le rendu Chart.js est piloté par le $effect en bas du script :
		// il se déclenche quand le canvas est (re)monté.
	}

	function renderDashCharts() {
		if (barChart) barChart.destroy();
		if (pieChart) pieChart.destroy();
		const cs = getComputedStyle(document.documentElement);

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
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', 'year_desc');
		return `${base}/api/publications/export.csv?${params}`;
	}

	async function excludeAuthorship(authorshipId: number, pubId: number) {
		if (!confirm('Exclure ce lien auteur–publication ? Il ne sera pas recréé automatiquement.')) return;
		await authorships.exclude(authorshipId);
		pubs.items = pubs.items.filter(p => p.id !== pubId);
	}

	function onTabSwitch(tab: string) {
		if (tab === 'dashboard' && !dashboardLoaded) loadDashboard();
		if (tab === 'publications' && pubs.items.length === 0 && pubs.total === 0) { facets.load(); pubs.load(); }
		if (tab === 'theses' && !thesesLoaded) loadTheses();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	let lastLoadedId = $state("");

	async function loadProfile(id: string) {
		if (id === lastLoadedId) return;
		lastLoadedId = id;
		error = false;
		profile = null;
		thesesLoaded = false;
		addrLoaded = false;
		dashboardLoaded = false;
		try {
			const profileData = await api<ProfileResponse>(`/api/persons/${id}/profile`);
			profile = profileData.person;
			identifiers = profileData.identifiers;
			authors = profileData.authors;
			thesesCount = profileData.theses_count;
		} catch {
			error = true;
			return;
		}
		if (activeTab === 'dashboard') loadDashboard();
		else if (activeTab === 'addresses') loadAddresses();
		else if (activeTab === 'theses') loadTheses();
		else if (activeTab === 'publications') { facets.load(); pubs.load(); }
	}

	onMount(async () => {
		canGoBack = ((window as any).navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));
		auth.check().then(d => { isAdmin = !!d.authenticated; }).catch(() => {});
		if (personId) await loadProfile(personId);
	});

	// Recharger quand personId change (navigation client-side)
	$effect(() => {
		if (personId) loadProfile(personId);
	});

	// (Re)render des charts dès que le canvas est monté avec data dispo.
	// Couvre à la fois le 1er affichage et les retours sur l'onglet après
	// que le {#if} ait détruit/remonté le canvas.
	$effect(() => {
		if (activeTab === 'dashboard' && dashboardLoaded && barCanvas && pieCanvas) {
			renderDashCharts();
		}
	});
</script>

<svelte:head>
	<title>{displayName || 'Personne'} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
<!-- svelte-ignore a11y_invalid_attribute -->
<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

{#if error}
	<div class="profile-header">
		<div class="no-results">Personne introuvable</div>
	</div>
{:else if !profile}
	<div class="profile-header">
		<div class="loading">Chargement...</div>
	</div>
{:else}
	<!-- Profile header -->
	<div class="profile-header">
		<h1 class="profile-name">
			{titleCase(profile.first_name)}
			<span class="profile-last">{titleCase(profile.last_name)}</span>
		</h1>
		<div class="profile-meta">
			{#if profile.role_title}
				<span class="role-badge">{profile.role_title}</span>
			{/if}
			{#if profile.department_name}
				<span>{profile.department_name}</span>
			{/if}
			{#if profile.start_date || profile.end_date}
				<span>
					Du {profile.start_date ? formatDate(profile.start_date) : '?'}
					— {profile.end_date ? formatDate(profile.end_date) : 'en poste'}
				</span>
			{/if}
			<IdentifiersCell
				orcids={allOrcids()}
				idhals={allIdhals()}
				idrefs={allIdrefs()}
			/>
		</div>
	</div>

	<!-- Tabs -->
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard' },
			{ id: 'publications', label: 'Publications', count: pubs.total },
			...(thesesCount > 0 ? [{ id: 'theses', label: 'Thèses', count: thesesCount }] : []),
			// TODO: onglet « Identités » désactivé — à déplacer côté admin
			// ou à supprimer définitivement (cf. PersonProfileResponse.authors).
			// { id: 'identities', label: 'Identités', count: authors.length },
			{ id: 'addresses', label: 'Adresses', count: addrLoaded ? addrTotal : undefined },
		]}
		onswitch={onTabSwitch}
	/>

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if !dashboardLoaded}
				<div class="loading">Chargement...</div>
			{:else}
				<div class="dash-grid">
					<div class="dash-card dash-card-wide">
						<h3>Sujets principaux</h3>
						<SubjectsCloud subjects={dashSubjects} />
					</div>
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
				{#if col('type')}<FacetDropdown label="Types" options={facets.options.docTypes} bind:selected={selectedDocTypes} onchange={onFilterChange} />{/if}
				{#if col('year')}<FacetDropdown label="Années" options={facets.options.years} bind:selected={selectedYears} onchange={onFilterChange} />{/if}
				{#if col('oa')}<FacetDropdown label="Accès" options={facets.options.access} bind:selected={selectedAccess} onchange={onFilterChange} />{/if}
				{#if col('oa_path')}<FacetDropdown label="Voies OA" options={facets.options.oa} bind:selected={selectedOa} onchange={onFilterChange} />{/if}
				{#if col('corr') && facets.options.corresponding.length}
					<FacetDropdown label="Corresp." options={facets.options.corresponding} bind:selected={selectedCorr} onchange={onFilterChange} />
				{/if}
				{#if facets.options.perimeter.length}
					<FacetDropdown label="UCA" options={facets.options.perimeter} bind:selected={selectedPerimeter} onchange={onFilterChange} />
				{/if}
				<FacetDropdown label="Pays" options={facets.options.countries} searchable bind:selected={selectedCountries} onchange={onFilterChange} />
				<PresenceFilterToggle label="Sources" items={SOURCE_ITEMS} bind:states={sourceStates} counts={facets.sourceCounts} onchange={onFilterChange} />
				<span class="toolbar-spacer"></span>
				<span class="count">{pubs.total} publication{pubs.total > 1 ? 's' : ''}</span>
				<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
			</div>
			<table class="pub-table">
				<thead>
					<tr>
						{#if isAdmin}<th style="width:28px"></th>{/if}
						{#if col('type')}<th style="width:80px">Type</th>{/if}
						{#if col('year')}<th style="width:40px" class="sortable" class:active={currentSort === 'year_desc' || currentSort === 'year_asc'} onclick={toggleSortYear}>An. {currentSort === 'year_asc' ? '↑' : '↓'}</th>{/if}
						<th class="sortable pub-col-title" class:active={currentSort === 'title' || currentSort === 'title_desc'} onclick={toggleSortTitle}>Titre {currentSort === 'title' ? '↑' : currentSort === 'title_desc' ? '↓' : ''}</th>
						{#if col('journal')}<th class="pub-col-journal">Revue</th>{/if}
						{#if col('labs')}<th style="width:80px">Labo(s)</th>{/if}
						{#if col('corr')}<th style="width:30px" title="Auteur correspondant">&#9993;</th>{/if}
						{#if col('apc')}<th style="width:60px">APC</th>{/if}
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
						<tr><td colspan={cv.visibleColumns.length + (isAdmin ? 1 : 0)} class="no-results">Aucune publication</td></tr>
					{:else}
						{#each pubs.items as p (p.id)}
							<tr>
								{#if isAdmin}
									<td class="exclude-cell">
										{#if p.authorship_id}
											<button class="exclude-btn" title="Exclure ce lien auteur–publication"
												onclick={() => excludeAuthorship(p.authorship_id!, p.id)}>✕</button>
										{/if}
									</td>
								{/if}
								{#if col('type')}<td>
									<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
								</td>{/if}
								{#if col('year')}<td>{p.pub_year || ''}</td>{/if}
								<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
								{#if col('journal')}<td class="journal-cell pub-col-journal"><span class="journal-clip">{p.journal || ''}</span></td>{/if}
								{#if col('labs')}<td>
									{#each p.lab_items || [] as lab}
										<a href="{base}/laboratories/{lab.id}" class="lab-tag">{lab.label}</a>
									{/each}
								</td>{/if}
								{#if col('corr')}<td class="corr-cell">
									{#if p.is_corresponding}
										<span title="Auteur correspondant">&#10003;</span>
									{/if}
								</td>{/if}
								{#if col('apc')}<td class="apc-cell">
									{#if p.apc}
										{@const ucaApc = p.apc.filter(a => a.budget_structure_id === 169)}
										{#if ucaApc.length > 0}
											<span class="apc-tag" class:apc-other={!p.is_corresponding}
												title={ucaApc.map(a => `${a.amount?.toLocaleString('fr-FR')} € (${a.lab_acronym || 'UCA'})`).join('\n') + (!p.is_corresponding ? '\nAuteur non correspondant' : '')}>
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
											<img src="{base}/icons/hal.ico" alt="HAL" />
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
									{#if p.openalex_id}
										<a href="https://openalex.org/{p.openalex_id}" target="_blank" rel="noopener" class="source-tag source-oa" title="OpenAlex: {p.openalex_id}">
											<img src="{base}/icons/openalex.png" alt="OA" />
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
											<img src="{base}/icons/wos.ico" alt="WoS" />
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
			<Pagination page={pubs.page} pages={pubs.pages} onchange={(p) => pubs.goToPage(p)} />
		</div>
	{/if}

	<!-- Tab: Thèses -->
	{#if activeTab === 'theses'}
		<div class="tab-content">
			{#if !thesesLoaded}
				<div class="loading">Chargement...</div>
			{:else if thesesSections.length === 0}
				<div class="no-results">Aucune thèse liée</div>
			{:else}
				{#each thesesSections as section (section.role)}
					<h3 class="thesis-role-heading">{section.label}</h3>
					<table class="pub-table">
						<thead>
							<tr>
								<th>Titre</th>
								<th style="width:100px">Labo</th>
								<th style="width:160px">Auteur</th>
								<th style="width:50px">Année</th>
							</tr>
						</thead>
						<tbody>
							{#each section.theses as t (t.id)}
								<tr>
									<td><a href="{base}/publications/{t.id}">{t.title}</a></td>
									<td>{#each t.structure_ids as sid}<a href="{base}/laboratories/{sid}" class="struct-tag">{thesesStructures[String(sid)]?.acronym || thesesStructures[String(sid)]?.name || `#${sid}`}</a>{/each}</td>
									<td>{#if t.author_person_id}<a href="{base}/persons/{t.author_person_id}">{t.author_name}</a>{:else}{t.author_name}{/if}</td>
									<td>{t.pub_year ?? ''}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/each}
			{/if}
		</div>
	{/if}

	<!--
		TODO: l'onglet « Identités » a été désactivé (cf. tabs ci-dessus, le
		HTML précédent est dans git). À ressortir côté admin si on a besoin du
		diagnostic « auteurs sources liés à la personne » (entité par entité,
		HAL / OpenAlex / WoS), sinon à supprimer définitivement avec
		PersonProfileResponse.authors et les types associés.
	-->


	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			{#if !addrLoaded}
				<div class="loading">Chargement...</div>
			{:else if addresses.length === 0}
				<div class="no-results">Aucune adresse</div>
			{:else}
				<table>
					<thead>
						<tr>
							<th>Adresse</th>
							<th style="width:160px">Structures</th>
						</tr>
					</thead>
					<tbody>
						{#each addresses as a (a.id)}
							<tr>
								<td class="addr-cell">{a.raw_text}</td>
								<td>
									{#if a.structures?.length}
										{#each a.structures as s (s.id)}
											<span class="struct-tag">{s.acronym || s.name}</span>
										{/each}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<Pagination page={addrPage} pages={addrPages} onchange={(p) => { addrPage = p; loadAddresses(); }} />
			{/if}
		</div>
	{/if}
{/if}

<style>
	/* Dashboard */
	.dash-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
	.dash-card-wide { grid-column: 1 / -1; }
	.dash-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 16px;
	}
	.dash-card h3 { font-size: 0.95rem; font-weight: 600; margin: 0 0 12px; }
	.chart-wrap { position: relative; height: 280px; }
	.oa-summary { text-align: center; font-size: 0.9rem; color: var(--muted); margin-top: 8px; }

	.thesis-role-heading {
		font-size: 1rem;
		font-weight: 600;
		margin: 20px 0 8px;
		color: var(--fg);
	}
	.thesis-role-heading:first-child { margin-top: 0; }
	.profile-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
		margin-bottom: 0;
	}
	.profile-name { font-size: 1.45rem; font-weight: 600; margin: 0 0 6px; }
	.profile-last { font-weight: 600; }
	.profile-meta {
		display: flex;
		gap: 16px;
		align-items: center;
		flex-wrap: wrap;
		font-size: 0.95rem;
		color: var(--muted);
	}
	.role-badge {
		display: inline-block;
		padding: 2px 8px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 0.85rem;
		color: var(--muted);
	}
	/* Shared table styles */
	.tab-content table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
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
	.tab-content tbody tr { border-bottom: 1px solid #f0efec; }
	.tab-content tbody tr:last-child { border-bottom: none; }
	.tab-content tbody tr:hover { background: #fafaf8; }
	.tab-content td { padding: 7px 10px; font-size: 0.95rem; vertical-align: middle; }
	.tab-content td a:not(.id-badge, .lab-tag, .struct-tag, .source-tag) { color: var(--accent); text-decoration: none; }
	.tab-content td a:not(.id-badge, .lab-tag, .struct-tag, .source-tag):hover { text-decoration: underline; }

	.source-tag-label { padding: 2px 7px; font-size: 0.8rem; }

	/* Publications tab */
	.pub-table td { vertical-align: top; }
	.pub-table th.sortable { cursor: pointer; user-select: none; }
	.pub-table th.sortable:hover { color: var(--accent); }
	.pub-table th.sortable.active { color: var(--accent); }
	.corr-cell { text-align: center; color: var(--accent); font-size: 0.85rem; }

	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
	.struct-tag {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--accent);
		font-weight: 500;
		margin: 1px 2px;
		text-decoration: none;
	}
	a.struct-tag:hover {
		background: #d0e3f4;
		text-decoration: none;
	}
	.exclude-cell { padding: 0 2px !important; text-align: center; vertical-align: middle; }
	.exclude-btn {
		background: none; border: none; cursor: pointer;
		color: #ccc; font-size: 0.85rem; padding: 2px 4px;
		border-radius: 3px; line-height: 1; transition: color 0.15s, background 0.15s;
	}
	.exclude-btn:hover { color: #c0392b; background: #fdeaea; }

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
	.col-menu-th { position: relative; }
</style>
