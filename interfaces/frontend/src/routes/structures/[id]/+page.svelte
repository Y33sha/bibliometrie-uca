<script lang="ts">
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/index.js';
	import { rorShortId, rorFullUrl } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectBars from '#lib/components/SubjectBars.svelte';
	import PersonsListView from '#lib/components/PersonsListView.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TabNav from '#lib/components/TabNav.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import ThesesListView from '#lib/components/ThesesListView.svelte';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PartnersTab from './PartnersTab.svelte';
	import StructureManagement from './StructureManagement.svelte';
	import { isAdmin } from '#lib/session.svelte.js';

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

	// Les onglets « Adresses » et « Gestion » sont réservés à la session admin.
	const validTabs = ['dashboard', 'publications', 'theses', 'persons', 'collaborations', ...(isAdmin() ? ['addresses', 'management'] : [])];
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

	// Dashboard tab : les publications passent par `PublicationsDashboard` ; la page ajoute les personnes présentes dans le SI RH et les sujets.
	let dashboardLoaded = $state(false);
	let rhPersonsCount = $state(0);
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	let dashSubjects: SubjectFrequency[] = $state([]);

	const tutelles = $derived(parents);


	// `useUrlFilters` ne gère ici que les keys cross-onglets (tab, addresses). Les filtres publications/thèses/personnes sont gérés par leurs ListView.
	const url = useUrlFilters({
		basePath: () => `/structures/${labId}`,
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
		// Le décompte des personnes reprend les réglages par défaut de l'onglet Personnes : présentes dans le SI RH, retenues, actives.
		const persons = new URLSearchParams({ lab_id: String(labId), has_rh: 'true', exclusion: 'none', active: 'true', per_page: '1' });
		const [personsPage, subjects] = await Promise.all([
			api<{ total: number }>(`/api/persons?${persons}`, { key: 'lab-rh-persons' }),
			api<SubjectFrequency[]>(`/api/structures/${labId}/subjects?limit=30`, {
				key: 'lab-subjects',
			}),
		]);
		rhPersonsCount = personsPage.total;
		dashSubjects = subjects;
		dashboardLoaded = true;
	}

	// En-tête de la fiche : la structure, ses tutelles et son nombre de thèses. Relu après une modification depuis l'onglet « Gestion ».
	async function loadProfile(): Promise<boolean> {
		try {
			const profileData = await api<LabProfile>(`/api/structures/${labId}`);
			lab = profileData.structure;
			parents = profileData.parents;
			children = profileData.children;
			thesesCount = profileData.theses_count;
			return true;
		} catch {
			error = true;
			return false;
		}
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

		if (!(await loadProfile())) return;
		// Load data for the active tab (publications est auto-géré).
		if (activeTab === 'dashboard') {
			loadDashboard();
		} else if (activeTab === 'addresses') {
			addresses.load();
		}
	});
</script>

<svelte:head>
	<title>{pageTitle(lab ? structureLabel(lab) : 'Structure')}</title>
</svelte:head>

<Breadcrumb trail={[{ label: 'Labos', path: 'structures' }]} current={lab?.acronym || lab?.name} />

{#if error}
	<div class="no-results">Structure introuvable</div>
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
			...(isAdmin()
				? [
						{ id: 'addresses', label: 'Adresses' },
						{ id: 'management', label: 'Gestion' },
					]
				: []),
		]}
		onswitch={onTabSwitch}
		afterNavigate={syncUrl}
	/>

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if lab}
				<PublicationsDashboard
					context={{ kind: 'lab', id: lab.id }}
					apiKey="lab-dashboard"
					figures={dashboardLoaded && rhPersonsCount > 0
						? [{ value: rhPersonsCount.toLocaleString('fr-FR'), label: 'personnes (SI RH)' }]
						: []}
				>
					<div class="dash-card dash-card-wide">
						<h2>Sujets principaux</h2>
						<SubjectBars subjects={dashSubjects} />
					</div>
				</PublicationsDashboard>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`lab-${lab.id}-publications`}
				context={{ kind: 'lab', id: lab.id }}
				basePath={`/structures/${labId}`}
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
						<TableStatusRow loading={addresses.loading} error={addresses.error} colspan={2} emptyText="Aucune adresse" />
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

	<!-- Tab: Gestion -->
	{#if activeTab === 'management'}
		<div class="tab-content">
			<StructureManagement id={lab.id} onupdated={loadProfile} />
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
