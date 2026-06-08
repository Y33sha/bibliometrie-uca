<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api, auth, authorships } from '$lib/api';
	import { titleCase, formatDate } from '$lib/utils';
	import { Chart, registerables } from 'chart.js';
	import ChartDataLabels from 'chartjs-plugin-datalabels';
	Chart.register(...registerables, ChartDataLabels);
	import IdentifiersCell from '$lib/components/IdentifiersCell.svelte';
	import SubjectsCloud from '$lib/components/SubjectsCloud.svelte';
	import TabNav from '$lib/components/TabNav.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
	import { confirmDialog } from '$lib/dialogs.svelte';
	import type { components } from '$lib/api/schema';

	const personId = $derived($page.params.id);
	let canGoBack = $state(false);

	// --- Types ---
	type Person = components['schemas']['PersonProfileCore'];
	type Identifier = components['schemas']['PersonIdentifierOut'];
	type Author = components['schemas']['PersonProfileAuthor'];
	type ProfileResponse = components['schemas']['PersonProfileResponse'];
	type Address = components['schemas']['PersonAddressOut'];
	type ThesisSection = components['schemas']['PersonThesesSection'];
	type ThesisStructInfo = components['schemas']['StructureRef'];
	type ThesesResponse = components['schemas']['PersonThesesResponse'];

	// --- State ---
	let profile = $state<Person | null>(null);
	let identifiers = $state<Identifier[]>([]);
	let authors = $state<Author[]>([]);
	let thesesCount = $state(0);
	let error = $state(false);
	let isAdmin = $state(false);

	// Total des publications après filtrage, remonté par PublicationsListView.
	let pubsTotal = $state(0);

	const activeTab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab');
			return t === 'publications' || t === 'theses' || t === 'addresses' ? t : 'dashboard';
		})()
	);

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

	async function excludeAuthorship(authorshipId: number) {
		if (!(await confirmDialog({ message: 'Exclure ce lien auteur–publication ? Il ne sera pas recréé automatiquement.', danger: true }))) {
			return false;
		}
		await authorships.exclude(authorshipId);
		return true;
	}

	function onTabSwitch(tab: string) {
		// L'onglet "publications" est géré par <PublicationsListView> qui
		// charge ses données dans son propre onMount à chaque (re)montage.
		if (tab === 'dashboard' && !dashboardLoaded) loadDashboard();
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
			const profileData = await api<ProfileResponse>(`/api/persons/${id}`);
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
		// publications : géré par <PublicationsListView> qui charge tout seul.
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
			{ id: 'publications', label: 'Publications', count: pubsTotal },
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
			<PublicationsListView
				apiKey={`person-${personId}-pubs`}
				externalFilters={{
					personId: Number(personId),
					personLabel: displayName,
				}}
				basePath={`/persons/${personId}`}
				showFilterBanner={false}
				showCorrespondingColumn
				showPerimeterFacet
				showAdminExclude={isAdmin}
				onExcludeAuthorship={excludeAuthorship}
				apcMode="person-uca"
				perPage={50}
				onTotalChange={(t) => (pubsTotal = t)}
			/>
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
								<th style="width:160px">Auteur</th>
								<th>Titre</th>
								<th style="width:100px">Labo</th>
								<th style="width:50px">Année</th>
							</tr>
						</thead>
						<tbody>
							{#each section.theses as t (t.id)}
								<tr>
									<td>{#if t.author_person_id}<a href="{base}/persons/{t.author_person_id}">{t.author_name}</a>{:else}{t.author_name ?? ''}{/if}</td>
									<td><a href="{base}/publications/{t.id}">{t.title}</a></td>
									<td>{#each t.structure_ids as sid}<a href="{base}/laboratories/{sid}" class="struct-tag">{thesesStructures[String(sid)]?.acronym || thesesStructures[String(sid)]?.name || `#${sid}`}</a>{/each}</td>
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
		background: var(--border-subtle);
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
	.tab-content td { padding: 7px 10px; font-size: 0.95rem; vertical-align: middle; }
	.tab-content td a:not(.id-badge, .lab-tag, .struct-tag, .source-tag) { color: var(--accent); text-decoration: none; }
	.tab-content td a:not(.id-badge, .lab-tag, .struct-tag, .source-tag):hover { text-decoration: underline; }

	.source-tag-label { padding: 2px 7px; font-size: 0.8rem; }

	/* Theses tab utilise aussi .pub-table */
	.pub-table td { vertical-align: top; }

	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
	.struct-tag {
		display: inline-block;
		padding: 2px 7px;
		background: var(--accent-light);
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
