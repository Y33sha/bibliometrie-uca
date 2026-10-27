<script lang="ts">
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import { api, apiDetail } from '#lib/api/index.js';
	import { docTypeColorVar, docTypeLabel, oaStatusLabel } from '#lib/labels.js';
	import TabNav from '#lib/components/TabNav.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import SerialsListView from '#lib/components/SerialsListView.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
	import DoughnutChart from '#lib/components/charts/DoughnutChart.svelte';
	import { cssVar, oaStatusColor } from '#lib/components/charts/cssVar.js';
	import SubjectsCloud from '#lib/components/SubjectsCloud.svelte';
	import type { components } from '#lib/api/schema.js';

	type PublisherDetail = components['schemas']['Publisher'];
	type PublisherDashboard = components['schemas']['PublisherDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	type EnumOption = components['schemas']['EnumOption'];

	const publisherId = $derived(Number(page.params.id));

	const validTabs = ['dashboard', 'serials', 'monographs', 'publications'];
	const activeTab = $derived(
		(() => {
			const t = page.url.searchParams.get('tab');
			return t && validTabs.includes(t) ? t : 'dashboard';
		})()
	);

	let publisher = $state<PublisherDetail | null>(null);
	let error = $state(false);
	let dashboard = $state<PublisherDashboard | null>(null);
	let subjects = $state<SubjectFrequency[]>([]);
	let dashboardLoaded = $state(false);

	// Label FR du publisher_type, affiché dans l'en-tête de la page.
	let publisherTypeLabels: Record<string, string> = $state({});

	// Distributions en segments pour les doughnuts, chaque type dans sa couleur. Pas de notion d'« attendu » au niveau éditeur, agrégat multi-revues.
	const docTypeSegments = $derived(
		(dashboard?.doc_types ?? []).map((d) => ({
			label: d.doc_type ? docTypeLabel(d.doc_type) : '(non renseigné)',
			value: d.count,
			color: cssVar(docTypeColorVar(d.doc_type ?? 'misc'))
		}))
	);
	const oaStatusSegments = $derived(
		(dashboard?.oa_statuses ?? []).map((o) => ({
			label: o.oa_status ? oaStatusLabel(o.oa_status) : '(non renseigné)',
			value: o.count,
			color: oaStatusColor(o.oa_status)
		}))
	);

	async function loadPublisher() {
		try {
			publisher = await apiDetail<PublisherDetail>(`/api/publishers/${publisherId}`);
		} catch {
			error = true;
		}
	}

	async function loadTypeLabels() {
		const publicationOptions = await api<EnumOption[]>('/api/publishers/types');
		publisherTypeLabels = Object.fromEntries(publicationOptions.map((o) => [o.value, o.label_fr]));
	}

	async function loadDashboard() {
		if (dashboardLoaded) return;
		const [d, s] = await Promise.all([
			api<PublisherDashboard>(`/api/publishers/${publisherId}/dashboard`, {
				key: 'p-dashboard'
			}),
			api<SubjectFrequency[]>(`/api/publishers/${publisherId}/subjects?limit=20`, {
				key: 'p-subjects'
			})
		]);
		dashboard = d;
		subjects = s;
		dashboardLoaded = true;
	}

	function onTabSwitch(tab: string) {
		if (tab === 'dashboard') loadDashboard();
	}

	onMount(async () => {
		await Promise.all([loadPublisher(), loadTypeLabels()]);
		if (activeTab === 'dashboard') loadDashboard();
		await tick();
	});

</script>

<svelte:head>
	<title>{pageTitle(publisher?.name ?? 'Éditeur')}</title>
</svelte:head>

	<Breadcrumb trail={[{ label: 'Éditeurs', path: 'publishers' }]} current={publisher?.name} />

{#if error}
	<div class="no-results">Éditeur introuvable</div>
{:else if !publisher}
	<div class="loading">Chargement…</div>
{:else}
	<!-- Header -->
	<div class="entity-header">
		<h1 class="entity-title">
			{publisher.name}
		</h1>
		<div class="entity-meta">
			<span class="entity-meta-label">Type</span>
			<span class="entity-tag">
				{publisherTypeLabels[publisher.publisher_type] ?? publisher.publisher_type}
			</span>
			{#if publisher.country}
				<span class="entity-meta-label">Pays</span>
				<span class="entity-tag">{publisher.country.toUpperCase()}</span>
			{/if}
			{#if publisher.openalex_id}
				<span class="entity-meta-label">OpenAlex</span>
				<span class="id-badge">{publisher.openalex_id}</span>
			{/if}
		</div>
		{#if publisher.doi_prefixes.length > 0}
			<div class="entity-meta">
				<span class="entity-meta-label">Préfixes DOI</span>
				{#each publisher.doi_prefixes as p (p.prefix)}
					<span class="id-badge" title="RA: {p.ra}">{p.prefix}</span>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Tabs -->
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard' },
			{ id: 'serials', label: 'Publications en série' },
			{ id: 'monographs', label: 'Monographies' },
			{ id: 'publications', label: 'Publications' }
		]}
		onswitch={onTabSwitch}
	/>

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if !dashboardLoaded || !dashboard}
				<div class="loading">Chargement…</div>
			{:else}
				<div class="dash-grid">
					<div class="dash-card dash-card-wide">
						<h2>Sujets principaux</h2>
						{#if subjects.length === 0}
							<p class="muted">Aucun sujet (les sujets génériques sont exclus du top).</p>
						{:else}
							<SubjectsCloud {subjects} />
						{/if}
					</div>

					<div class="dash-card">
						<h2>Types de documents ({dashboard.total_publications})</h2>
						{#if dashboard.doc_types.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<DoughnutChart segments={docTypeSegments} />
						{/if}
					</div>

					<div class="dash-card">
						<h2>Statuts Open Access</h2>
						{#if dashboard.oa_statuses.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<DoughnutChart segments={oaStatusSegments} />
						{/if}
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications en série -->
	{#if activeTab === 'serials'}
		<div class="tab-content">
			<SerialsListView
				apiKey={`publisher-${publisherId}-journals`}
				externalFilters={{ publisherId }}
			/>
		</div>
	{/if}

	<!-- Tab: Monographies -->
	{#if activeTab === 'monographs'}
		<div class="tab-content">
			<MonographsListView apiKey={`publisher-${publisherId}-monographs`} externalFilters={{ publisherId }} />
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`publisher-${publisherId}-publications`}
				context={{ kind: 'publisher', id: publisherId }}
				basePath={`/publishers/${publisherId}`}
				perPage={50}
			/>
		</div>
	{/if}
{/if}

<style>

	.loading, .no-results { padding: 20px; color: var(--muted); }

	.muted { color: var(--muted); }
</style>
