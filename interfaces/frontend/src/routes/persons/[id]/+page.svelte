<script lang="ts">
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { api, apiDetail, contributions } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { titleCase, formatDate } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import OaBar from '#lib/components/charts/OaBar.svelte';
	import PublicationsByYearChart from '#lib/components/charts/PublicationsByYearChart.svelte';
	import KeyFigures from '#lib/components/KeyFigures.svelte';
	import SubjectBars from '#lib/components/SubjectBars.svelte';
	import IdentifiersCell from '#lib/components/IdentifiersCell.svelte';
	import TabNav from '#lib/components/TabNav.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import { confirmDialog } from '#lib/dialogs.svelte.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import type { components } from '#lib/api/schema.js';

	const personId = $derived(page.params.id);
	// --- Types ---
	type Person = components['schemas']['PersonProfileCore'];
	type Identifier = components['schemas']['PersonIdentifierOut'];
	type ProfileResponse = components['schemas']['PersonProfileResponse'];
	type Address = components['schemas']['PersonAddressOut'];
	type ThesisSection = components['schemas']['PersonThesesSection'];
	type ThesisStructInfo = components['schemas']['StructureRef'];
	type ThesesResponse = components['schemas']['PersonThesesResponse'];

	// --- State ---
	let profile = $state<Person | null>(null);
	let identifiers = $state<Identifier[]>([]);
	let thesesCount = $state(0);
	let error = $state(false);

	const activeTab = $derived(
		(() => {
			const t = page.url.searchParams.get('tab');
			// L'onglet « Adresses » est réservé à la session admin.
			return t === 'publications' || t === 'theses' || (t === 'addresses' && isAdmin()) ? t : 'dashboard';
		})()
	);

	// Theses tab
	let thesesSections: ThesisSection[] = $state([]);
	let thesesTotal = $state(0);
	let thesesStructures = $state<Record<string, ThesisStructInfo>>({});
	let thesesLoaded = $state(false);

	// Addresses tab
	const addresses = usePaginatedFetch<Address>({
		endpoint: () => `/api/persons/${personId}/addresses`,
		itemsKey: 'addresses',
		apiKey: 'person-detail-addresses',
		buildParams: () => new URLSearchParams(),
		pageParam: null,
	});
	// Remis à `false` à chaque changement de personne.
	let addrLoaded = $state(false);

	// Dashboard tab
	type DashboardResponse = components['schemas']['PersonDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	let dashboardLoaded = $state(false);
	let dashPubsByYear: { year: number; count: number }[] = $state([]);
	let dashOa = $state({ open_access: 0, embargoed: 0, closed: 0, unknown: 0, total: 0 });
	let dashSubjects: SubjectFrequency[] = $state([]);

	const displayName = $derived(
		profile
			? `${titleCase(profile.first_name)} ${titleCase(profile.last_name)}`
			: ''
	);

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
		await addresses.load();
		addrLoaded = true;
	}

	async function loadDashboard() {
		const [data, subjects] = await Promise.all([
			api<DashboardResponse>(`/api/persons/${personId}/dashboard`, { key: 'person-detail-dashboard' }),
			api<SubjectFrequency[]>(`/api/persons/${personId}/subjects?limit=30`, { key: 'person-detail-subjects' }),
		]);
		dashPubsByYear = data.publications_by_year;
		dashOa = data.oa;
		dashSubjects = subjects;
		dashboardLoaded = true;
	}

	async function excludeContribution(contributionId: number) {
		if (!(await confirmDialog({ message: 'Exclure ce lien auteur–publication ? Il ne sera pas recréé automatiquement.', danger: true }))) {
			return false;
		}
		await contributions.exclude(contributionId);
		return true;
	}

	function onTabSwitch(tab: string) {
		// L'onglet "publications" est géré par <PublicationsListView> qui charge ses données dans son propre onMount à chaque (re)montage.
		if (tab === 'dashboard' && !dashboardLoaded) loadDashboard();
		if (tab === 'theses' && !thesesLoaded) loadTheses();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	async function loadProfile(id: string) {
		try {
			const profileData = await apiDetail<ProfileResponse>(`/api/persons/${id}`);
			profile = profileData.person;
			identifiers = profileData.identifiers;
			thesesCount = profileData.theses_count;
		} catch {
			error = true;
			return;
		}
		if (activeTab === 'dashboard') loadDashboard();
		else if (activeTab === 'addresses') loadAddresses();
		else if (activeTab === 'theses') loadTheses();
		// publications : géré par <PublicationsListView> qui charge tout seul.
	}

	onMount(async () => {
		if (personId) await loadProfile(personId);
	});

</script>

<svelte:head>
	<title>{pageTitle(displayName || 'Personne')}</title>
</svelte:head>

<Breadcrumb trail={[{ label: 'Chercheurs', path: 'persons' }]} current={displayName} />

{#if error}
	<div class="no-results">Personne introuvable</div>
{:else if !profile}
	<div class="loading">Chargement…</div>
{:else}
	<!-- Profile header -->
	<div class="entity-header">
		<h1 class="entity-title">
			{titleCase(profile.first_name)}
			<span>{titleCase(profile.last_name)}</span>
		</h1>
		<div class="entity-meta">
			{#if profile.role_title}
				<span class="entity-tag">{profile.role_title}</span>
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
			<IdentifiersCell {identifiers} />
		</div>
	</div>

	<!-- Tabs -->
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard' },
			{ id: 'publications', label: 'Publications' },
			...(thesesCount > 0 ? [{ id: 'theses', label: 'Thèses' }] : []),
			...(isAdmin() ? [{ id: 'addresses', label: 'Adresses' }] : []),
		]}
		onswitch={onTabSwitch}
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
						...(thesesCount > 0 ? [{ value: thesesCount.toLocaleString('fr-FR'), label: 'thèses (direction ou jury)' }] : []),
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
				apiKey={`person-${personId}-publications`}
				externalFilters={{
					personId: Number(personId),
					personLabel: displayName,
				}}
				basePath={`/persons/${personId}`}
				showFilterBanner={false}
				showCorrespondingColumn
				showPerimeterFacet
				showAdminExclude={isAdmin()}
				onExcludeContribution={excludeContribution}
				apcMode="person"
				perPage={50}
			/>
		</div>
	{/if}

	<!-- Tab: Thèses -->
	{#if activeTab === 'theses'}
		<div class="tab-content">
			{#if !thesesLoaded}
				<div class="loading">Chargement…</div>
			{:else if thesesSections.length === 0}
				<div class="no-results">Aucune thèse liée</div>
			{:else}
				{#each thesesSections as section (section.role)}
					<h3 class="thesis-role-heading">{section.label}</h3>
					<table class="data-table">
						<thead>
							<tr>
								<th style="width:160px">Auteur</th>
								<th>Titre</th>
								<th style="width:100px">Labo</th>
								<th style="width:50px">Année</th>
							</tr>
						</thead>
						<tbody>
							{#each section.theses as t (t.id)}
								<tr>
									<td>{#if t.author_person_id}<a href={resolve(`persons/${t.author_person_id}`)}>{titleCase(t.author_name)}</a>{:else}{t.author_name ? titleCase(t.author_name) : ''}{/if}</td>
									<td><a href={resolve(`publications/${t.id}`)}><PublicationTitle titre={t.title} /></a></td>
									<td>{#each t.structure_ids as sid}<a href={resolve(`structures/${sid}`)} class="structure-tag">{thesesStructures[String(sid)]?.acronym || thesesStructures[String(sid)]?.name || `#${sid}`}</a>{/each}</td>
									<td>{t.publication_year ?? ''}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/each}
			{/if}
		</div>
	{/if}

	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			{#if !addrLoaded}
				<div class="loading">Chargement…</div>
			{:else if addresses.items.length === 0}
				<div class="no-results">Aucune adresse</div>
			{:else}
				<table class="data-table">
					<thead>
						<tr>
							<th>Adresse</th>
							<th style="width:160px">Structures</th>
						</tr>
					</thead>
					<tbody>
						{#each addresses.items as a (a.id)}
							<tr>
								<td class="addr-cell">{a.raw_text}</td>
								<td>
									{#if a.structures?.length}
										{#each a.structures as s (s.id)}
											<span class="structure-tag">{structureLabel(s)}</span>
										{/each}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<Pagination page={addresses.page} pages={addresses.pages} onchange={(p) => { addresses.page = p; addresses.load(); }} />
			{/if}
		</div>
	{/if}
{/if}

<style>
	.thesis-role-heading {
		font-size: 1rem;
		font-weight: 600;
		margin: 20px 0 8px;
		color: var(--text);
	}
	.thesis-role-heading:first-child { margin-top: 0; }


	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
</style>
