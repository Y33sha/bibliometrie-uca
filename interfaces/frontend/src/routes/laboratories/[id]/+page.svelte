<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { rorShortId, rorFullUrl } from '$lib/utils';
	import BarChart from '$lib/components/charts/BarChart.svelte';
	import DoughnutChart from '$lib/components/charts/DoughnutChart.svelte';
	import PersonsListView from '$lib/components/PersonsListView.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import TabNav from '$lib/components/TabNav.svelte';
	import ThesesListView from '$lib/components/ThesesListView.svelte';
	import { useUrlFilters } from '$lib/composables/useUrlFilters.svelte';
	import SubjectsCloud from '$lib/components/SubjectsCloud.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';

	const labId = $derived($page.params.id);
	let canGoBack = $state(false);

	// --- Types ---
	import type { components } from '$lib/api/schema';
	type Structure = components['schemas']['StructureOut'];
	type RelatedStructure = components['schemas']['RelatedStructureOut'];
	type LabProfile = components['schemas']['StructureDetailResponse'];
	type LabAddress = components['schemas']['StructureAddressOut'];
	type AddressesResponse = components['schemas']['StructureAddressesResponse'];

	// --- State ---
	let lab: Structure | null = $state(null);
	let parents: RelatedStructure[] = $state([]);
	let children: RelatedStructure[] = $state([]);
	let thesesCount = $state(0);
	let error = $state(false);

	const validTabs = ['dashboard', 'publications', 'theses', 'persons', 'addresses'];
	const activeTab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab');
			return t && validTabs.includes(t) ? t : 'dashboard';
		})()
	);

	// Addresses tab
	let addresses: LabAddress[] = $state([]);
	let addrPage = $state(1);
	let addrPages = $state(1);
	let addrLoaded = $state(false);

	// Dashboard tab
	let dashboardLoaded = $state(false);
	let dashPubsByYear: { year: number; count: number }[] = $state([]);
	let dashOa: { open_access: number; embargoed: number; closed: number; unknown: number; total: number } = $state({ open_access: 0, embargoed: 0, closed: 0, unknown: 0, total: 0 });
	let dashCollab: { total_articles: number; international: number; domestic: number } = $state({ total_articles: 0, international: 0, domestic: 0 });
	let dashTopCountries: { code: string; name: string; count: number }[] = $state([]);
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	let dashSubjects: SubjectFrequency[] = $state([]);

	const oaSegments = $derived([
		{ label: 'Open Access', value: dashOa.open_access, color: '#2a7d4f' },
		{ label: 'Sous embargo', value: dashOa.embargoed, color: '#b08900' },
		{ label: 'Closed', value: dashOa.closed, color: '#c0392b' },
		{ label: 'Indéterminé', value: dashOa.unknown, color: '#ccc' }
	]);
	const collabSegments = $derived([
		{ label: 'International', value: dashCollab.international, color: '#3b6b9e' },
		{ label: 'Domestique', value: dashCollab.domestic, color: '#e0e0e0' }
	]);

	const tutelles = $derived(parents.filter((p) => p.relation_type === 'est_tutelle_de'));
	const partenaires = $derived(parents.filter((p) => p.relation_type === 'est_partenaire_de'));


	// `useUrlFilters` ne gère ici que les keys cross-onglets (tab, addresses).
	// Les filtres publications/thèses/personnes sont gérés par leurs ListView.
	const url = useUrlFilters({
		basePath: () => `/laboratories/${labId}`,
		filters: {
			tab:              { type: 'single', urlKey: 'tab', defaultValue: 'dashboard' },
			addrPage:         { type: 'page',   urlKey: 'apage' },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		url.syncUrl(() => ({
			tab: activeTab,
			addrPage,
		}));
	}

	async function loadAddresses() {
		const params = new URLSearchParams({
			page: String(addrPage),
			per_page: '50'
		});
		const data = await api<AddressesResponse>(
			`/api/structures/${labId}/addresses?${params}`, { key: 'lab-addresses' }
		);
		addresses = data.addresses;
		addrPages = data.pages;
		addrPage = data.page;
		addrLoaded = true;
	}

	async function loadDashboard() {
		const [data, subjects] = await Promise.all([
			api<{
				pubs_by_year: { year: number; count: number }[];
				oa: { open_access: number; embargoed: number; closed: number; unknown: number; total: number };
				collab: { total_articles: number; international: number; domestic: number };
				top_countries: { code: string; name: string; count: number }[];
			}>(`/api/structures/${labId}/dashboard`, { key: 'lab-dashboard' }),
			api<SubjectFrequency[]>(`/api/structures/${labId}/subjects?limit=30`, {
				key: 'lab-subjects',
			}),
		]);
		dashPubsByYear = data.pubs_by_year;
		dashOa = data.oa;
		dashCollab = data.collab;
		dashTopCountries = data.top_countries;
		dashSubjects = subjects;
		dashboardLoaded = true;
	}

	function onTabSwitch(tab: string) {
		// Les onglets "publications" et "theses" sont gérés par leurs ListView
		// respectives, qui chargent leurs données dans leur propre onMount.
		if (tab === 'dashboard') loadDashboard();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	onMount(async () => {
		canGoBack = ((window as any).navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));

		// Restore cross-tab state from URL (les filtres publications sont
		// restaurés par PublicationsListView lui-même).
		const restored = url.restoreFromUrl($page.url.searchParams);
		if (restored.addrPage) addrPage = restored.addrPage as number;

		try {
			const profileData = await api<LabProfile>(`/api/structures/${labId}`);
			lab = profileData.structure;
			parents = profileData.parents;
			children = profileData.children;
			thesesCount = profileData.theses_count;
		} catch {
			error = true;
			return;
		}
		// Load data for the active tab (publications est auto-géré).
		if (activeTab === 'dashboard') {
			loadDashboard();
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
		<div class="loading">Chargement…</div>
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
					<a href={rorFullUrl(lab.ror_id)} target="_blank" rel="noopener" class="id-badge">
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
			{ id: 'dashboard', label: 'Dashboard' },
			{ id: 'publications', label: 'Publications' },
			...(thesesCount > 0 ? [{ id: 'theses', label: 'Thèses' }] : []),
			{ id: 'persons', label: 'Personnes' },
			{ id: 'addresses', label: 'Adresses' },
		]}
		onswitch={onTabSwitch}
		afterNavigate={syncUrl}
	/>

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if !dashboardLoaded}
				<div class="loading">Chargement…</div>
			{:else}
				<div class="dash-grid">
					<div class="dash-card dash-card-wide">
						<h3>Sujets principaux</h3>
						<SubjectsCloud subjects={dashSubjects} />
					</div>
					<div class="dash-card">
						<h3>Publications par année</h3>
						<BarChart
							labels={dashPubsByYear.map((d) => String(d.year))}
							values={dashPubsByYear.map((d) => d.count)}
							datasetLabel="Publications"
						/>
					</div>
					<div class="dash-card">
						<h3>Open Access</h3>
						<DoughnutChart segments={oaSegments} />
						{#if dashOa.total > 0}
							<div class="oa-summary">
								{Math.round(dashOa.open_access / dashOa.total * 100)} % Open Access
								({dashOa.open_access.toLocaleString('fr-FR')} / {dashOa.total.toLocaleString('fr-FR')})
							</div>
						{/if}
					</div>
					<div class="dash-card">
						<h3>Collaborations internationales (articles)</h3>
						<DoughnutChart segments={collabSegments} />
						{#if dashCollab.total_articles > 0}
							<div class="oa-summary">
								{Math.round(dashCollab.international / dashCollab.total_articles * 100)} % international
								({dashCollab.international.toLocaleString('fr-FR')} / {dashCollab.total_articles.toLocaleString('fr-FR')} articles)
							</div>
						{/if}
					</div>
					<div class="dash-card">
						<h3>Top 5 pays partenaires (articles)</h3>
						<BarChart
							labels={dashTopCountries.map((c) => c.name)}
							values={dashTopCountries.map((c) => c.count)}
							datasetLabel="Articles"
							color="#e8a838"
							horizontal
						/>
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`lab-${lab.id}-pubs`}
				externalFilters={{
					labId: lab.id,
					labLabel: lab.acronym || lab.name,
					halCollection: lab.hal_collection ?? undefined,
				}}
				basePath={`/laboratories/${labId}`}
				showFilterBanner={false}
				showHalStatusColumn
				apcMode="lab"
				perPage={50}
			/>
		</div>
	{/if}

	<!-- Tab: Thèses -->
	{#if activeTab === 'theses'}
		<div class="tab-content">
			<ThesesListView labId={lab.id} urlSync={false} apiKey={`lab-${lab.id}-theses`} />
		</div>
	{/if}

	<!-- Tab: Personnes -->
	{#if activeTab === 'persons'}
		<div class="tab-content">
			<PersonsListView
				labId={lab.id}
				urlSync={false}
				apiKey={`lab-${lab.id}-persons`}
			/>
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
	.tutelle-tag { background: var(--accent-light); color: var(--accent); }
	.partner-tag { background: var(--border-subtle); color: var(--muted); }
	.id-badge { margin-right: 8px; }

	/* Dashboard */
	.dash-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
	@media (max-width: 760px) {
		.dash-grid { grid-template-columns: 1fr; }
	}
	.dash-card-wide { grid-column: 1 / -1; }
	.dash-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 16px;
		min-width: 0; /* autorise la cellule grid à rétrécir sous la largeur du canvas */
	}
	.dash-card h3 { font-size: 0.95rem; font-weight: 600; margin: 0 0 12px; }
	.oa-summary { text-align: center; font-size: 0.9rem; color: var(--muted); margin-top: 8px; }

	/* Shared table styles */
	.tab-content table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		/* pas d'overflow: hidden → le dropdown ColumnMenu peut déborder
		   sous la dernière ligne sans être clippé. Les coins arrondis
		   restent visuellement corrects grâce à border-collapse. */
	}
	.tab-content thead th {
		background: var(--surface);
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.tab-content tbody tr { border-bottom: 1px solid var(--border-subtle); }
	.tab-content tbody tr:last-child { border-bottom: none; }
	.tab-content tbody tr:hover { background: var(--surface-hover); }
	.tab-content td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }

	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
	.status-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 0.8rem;
		font-weight: 500;
	}
	.status-tag.confirmed { background: var(--success-light); color: var(--success); }
	.status-tag.pending { background: var(--border-subtle); color: var(--muted); }
</style>
