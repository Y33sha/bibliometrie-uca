<script lang="ts">
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { resolve } from '$app/paths';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/index.js';
	import { rorShortId, rorFullUrl } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import BarChart from '#lib/components/charts/BarChart.svelte';
	import DoughnutChart from '#lib/components/charts/DoughnutChart.svelte';
	import OaBar from '#lib/components/charts/OaBar.svelte';
	import PublicationsByYearChart from '#lib/components/charts/PublicationsByYearChart.svelte';
	import KeyFigures from '#lib/components/KeyFigures.svelte';
	import SubjectBars from '#lib/components/SubjectBars.svelte';
	import { cssVar } from '#lib/components/charts/cssVar.js';
	import PersonsListView from '#lib/components/PersonsListView.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TabNav from '#lib/components/TabNav.svelte';
	import ThesesListView from '#lib/components/ThesesListView.svelte';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PartnersTab from './PartnersTab.svelte';

	const labId = $derived(page.params.id);
	// --- Types ---
	import type { components } from '#lib/api/schema.js';
	type Structure = components['schemas']['StructureOut'];
	type RelatedStructure = components['schemas']['RelatedStructureOut'];
	type LabProfile = components['schemas']['StructureDetailResponse'];
	type LabAddress = components['schemas']['StructureAddressOut'];

	// --- State ---
	let lab: Structure | null = $state(null);
	let parents: RelatedStructure[] = $state([]);
	let children: RelatedStructure[] = $state([]);
	let thesesCount = $state(0);
	let error = $state(false);

	const validTabs = ['dashboard', 'publications', 'theses', 'persons', 'collaborations', 'addresses'];
	const activeTab = $derived(
		(() => {
			const t = page.url.searchParams.get('tab');
			return t && validTabs.includes(t) ? t : 'dashboard';
		})()
	);

	// Addresses tab
	const addresses = usePaginatedFetch<LabAddress>({
		endpoint: () => `/api/structures/${labId}/addresses`,
		itemsKey: 'addresses',
		apiKey: 'lab-addresses',
		buildParams: () => new URLSearchParams(),
		pageParam: 'apage',
	});

	// Dashboard tab
	let dashboardLoaded = $state(false);
	let dashPubsByYear: { year: number; count: number }[] = $state([]);
	let dashOa: { open_access: number; embargoed: number; closed: number; unknown: number; total: number } = $state({ open_access: 0, embargoed: 0, closed: 0, unknown: 0, total: 0 });
	let dashCollab: { total_articles: number; international: number; domestic: number } = $state({ total_articles: 0, international: 0, domestic: 0 });
	let dashTopCountries: { code: string; name: string; count: number }[] = $state([]);
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	let dashSubjects: SubjectFrequency[] = $state([]);

	const collabSegments = $derived([
		{ label: 'International', value: dashCollab.international, color: cssVar('accent-mid') },
		{ label: 'Domestique', value: dashCollab.domestic, color: cssVar('border') }
	]);

	const tutelles = $derived(parents);


	// `useUrlFilters` ne gère ici que les keys cross-onglets (tab, addresses). Les filtres publications/thèses/personnes sont gérés par leurs ListView.
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
			addrPage: addresses.page,
		}));
	}

	async function loadDashboard() {
		const [data, subjects] = await Promise.all([
			api<{
				publications_by_year: { year: number; count: number }[];
				oa: { open_access: number; embargoed: number; closed: number; unknown: number; total: number };
				collab: { total_articles: number; international: number; domestic: number };
				top_countries: { code: string; name: string; count: number }[];
			}>(`/api/structures/${labId}/dashboard`, { key: 'lab-dashboard' }),
			api<SubjectFrequency[]>(`/api/structures/${labId}/subjects?limit=30`, {
				key: 'lab-subjects',
			}),
		]);
		dashPubsByYear = data.publications_by_year;
		dashOa = data.oa;
		dashCollab = data.collab;
		dashTopCountries = data.top_countries;
		dashSubjects = subjects;
		dashboardLoaded = true;
	}

	function onTabSwitch(tab: string) {
		// Les onglets "publications" et "theses" sont gérés par leurs ListView respectives, qui chargent leurs données dans leur propre onMount.
		if (tab === 'dashboard') loadDashboard();
		if (tab === 'addresses' && !addresses.loaded) addresses.load();
	}

	onMount(async () => {
		// Restore cross-tab state from URL (les filtres publications sont restaurés par PublicationsListView lui-même).
		const restored = url.restoreFromUrl(page.url.searchParams);
		if (restored.addrPage) addresses.page = restored.addrPage as number;

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
			addresses.load();
		}
	});
</script>

<svelte:head>
	<title>{pageTitle(lab ? structureLabel(lab) : 'Laboratoire')}</title>
</svelte:head>

<Breadcrumb trail={[{ label: 'Labos', href: resolve('laboratories') }]} current={lab?.acronym || lab?.name} />

{#if error}
	<div class="no-results">Laboratoire introuvable</div>
{:else if !lab}
	<div class="loading">Chargement…</div>
{:else}
	<!-- Header -->
	<div class="entity-header">
		<h1 class="entity-title">
			{lab.name}
			{#if lab.acronym}
				<span class="entity-acronym">{lab.acronym}</span>
			{/if}
		</h1>
		<div class="entity-meta">
			{#if lab.ror_id}
				<span class="entity-meta-label">ROR</span>
				<a href={rorFullUrl(lab.ror_id)} target="_blank" rel="noopener" class="id-badge">
					{rorShortId(lab.ror_id)}
				</a>
			{/if}
			{#if lab.rnsr_id}
				<span class="entity-meta-label">RNSR</span>
				<span class="id-badge">{lab.rnsr_id}</span>
			{/if}
			{#if lab.hal_collection}
				<span class="entity-meta-label">HAL</span>
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
				<span class="entity-meta-label">Tutelles</span>
				{#each tutelles as t (t.id)}
					<span class="entity-tag entity-tag-accent">{structureLabel(t)}</span>
				{/each}
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
			{ id: 'collaborations', label: 'Collaborations' },
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
				<KeyFigures
					items={[
						{ value: dashOa.total.toLocaleString('fr-FR'), label: 'publications' },
						...(dashOa.total > 0
							? [{ value: `${Math.round((dashOa.open_access / dashOa.total) * 100)} %`, label: 'en open access', tone: 'open' as const }]
							: []),
						...(thesesCount > 0 ? [{ value: thesesCount.toLocaleString('fr-FR'), label: 'thèses' }] : []),
					]}
				/>
				<div class="dash-grid">
					<div class="dash-card">
						<h3>Publications par année</h3>
						<PublicationsByYearChart data={dashPubsByYear} />
					</div>
					<div class="dash-card">
						<h3>Open access</h3>
						<OaBar oa={dashOa} />
					</div>
					<div class="dash-card">
						<h3>Collaborations internationales (articles)</h3>
						<DoughnutChart segments={collabSegments} />
						{#if dashCollab.total_articles > 0}
							<div class="dash-summary">
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
							horizontal
						/>
					</div>
					<div class="dash-card dash-card-wide">
						<h3>Sujets principaux</h3>
						<SubjectBars subjects={dashSubjects} />
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`lab-${lab.id}-publications`}
				externalFilters={{
					labId: lab.id,
					labLabel: structureLabel(lab),
					halCollection: lab.hal_collection ?? undefined,
				}}
				basePath={`/laboratories/${labId}`}
				showFilterBanner={false}
				showHalStatusColumn
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

	<!-- Tab: Collaborations -->
	{#if activeTab === 'collaborations'}
		<div class="tab-content">
			<PartnersTab labId={lab.id} />
		</div>
	{/if}

	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			<table class="data-table">
				<thead>
					<tr>
						<th>Adresse</th>
						<th style="width:80px">Statut</th>
					</tr>
				</thead>
				<tbody>
					{#if addresses.items.length === 0}
						<tr><td colspan="2" class="no-results">Aucune adresse</td></tr>
					{:else}
						{#each addresses.items as a (a.id)}
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
			<Pagination page={addresses.page} pages={addresses.pages} onchange={(p) => { addresses.page = p; syncUrl(); addresses.load(); }} />
		</div>
	{/if}
{/if}

<style>


	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
	.status-tag {
		display: inline-block;
		padding: 2px 7px;
		border-radius: var(--radius);
		font-size: 0.8rem;
		font-weight: 500;
	}
	.status-tag.confirmed { background: var(--success-light); color: var(--success); }
	.status-tag.pending { background: var(--border-subtle); color: var(--muted); }
</style>
