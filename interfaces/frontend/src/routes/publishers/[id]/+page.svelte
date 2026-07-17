<script lang="ts">
	import { page } from '$app/stores';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { oaLabelsMap } from '$lib/labels';
	import { docTypeSingular } from '$lib/labels';
	import TabNav from '$lib/components/TabNav.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
	import JournalsListView from '$lib/components/JournalsListView.svelte';
	import DoughnutChart from '$lib/components/charts/DoughnutChart.svelte';
	import { oaStatusColor } from '$lib/components/charts/oaColors';
	import SubjectsCloud from '$lib/components/SubjectsCloud.svelte';
	import type { components } from '$lib/api/schema';

	type PublisherDetail = components['schemas']['Publisher'];
	type PublisherDashboard = components['schemas']['PublisherDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	type EnumOption = components['schemas']['EnumOption'];

	const publisherId = $derived(Number($page.params.id));

	const validTabs = ['dashboard', 'journals', 'publications'];
	const activeTab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab');
			return t && validTabs.includes(t) ? t : 'dashboard';
		})()
	);

	let publisher = $state<PublisherDetail | null>(null);
	let error = $state(false);
	let canGoBack = $state(false);

	let dashboard = $state<PublisherDashboard | null>(null);
	let subjects = $state<SubjectFrequency[]>([]);
	let dashboardLoaded = $state(false);

	// Label FR du publisher_type, affiché dans l'en-tête de la page.
	let publisherTypeLabels: Record<string, string> = $state({});

	// Distributions en segments pour les doughnuts (palette neutre ; pas de
	// notion d'« attendu » au niveau éditeur, agrégat multi-revues).
	const docTypeSegments = $derived(
		(dashboard?.doc_types ?? []).map((d) => ({
			label: d.doc_type ? (docTypeSingular[d.doc_type] ?? d.doc_type) : '(non renseigné)',
			value: d.count
		}))
	);
	const oaStatusSegments = $derived(
		(dashboard?.oa_statuses ?? []).map((o) => ({
			label: o.oa_status ? (oaLabelsMap[o.oa_status] ?? o.oa_status) : '(non renseigné)',
			value: o.count,
			color: oaStatusColor(o.oa_status)
		}))
	);

	async function loadPublisher() {
		try {
			publisher = await api<PublisherDetail>(`/api/publishers/${publisherId}`);
		} catch {
			error = true;
		}
	}

	async function loadTypeLabels() {
		const pubOpts = await api<EnumOption[]>('/api/publishers/types');
		publisherTypeLabels = Object.fromEntries(pubOpts.map((o) => [o.value, o.label_fr]));
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
		canGoBack =
			(window as any).navigation?.canGoBack ??
			document.referrer.startsWith(window.location.origin);
		await Promise.all([loadPublisher(), loadTypeLabels()]);
		if (activeTab === 'dashboard') loadDashboard();
		await tick();
	});

</script>

<svelte:head>
	<title>{publisher?.name ?? 'Éditeur'} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
	<!-- svelte-ignore a11y_invalid_attribute -->
	<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

{#if error}
	<div class="no-results">Éditeur introuvable</div>
{:else if !publisher}
	<div class="loading">Chargement…</div>
{:else}
	<!-- Header -->
	<div class="p-header">
		<h1 class="p-title">
			{publisher.name}
		</h1>
		<div class="p-meta">
			<div class="meta-row">
				<span class="meta-label">Type</span>
				<span class="type-tag">
					{publisherTypeLabels[publisher.publisher_type] ?? publisher.publisher_type}
				</span>
				{#if publisher.country}
					<span class="meta-label">Pays</span>
					<span class="type-tag">{publisher.country.toUpperCase()}</span>
				{/if}
				{#if publisher.openalex_id}
					<span class="meta-label">OpenAlex</span>
					<span class="id-badge">{publisher.openalex_id}</span>
				{/if}
			</div>
			{#if publisher.doi_prefixes.length > 0}
				<div class="meta-row">
					<span class="meta-label">Préfixes DOI</span>
					{#each publisher.doi_prefixes as p (p.prefix)}
						<span class="id-badge" title="RA: {p.ra}">{p.prefix}</span>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	<!-- Tabs -->
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard' },
			{ id: 'journals', label: 'Revues' },
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
						<h3>Sujets dominants</h3>
						{#if subjects.length === 0}
							<p class="muted">Aucun sujet (les sujets génériques sont exclus du top).</p>
						{:else}
							<SubjectsCloud {subjects} />
						{/if}
					</div>

					<div class="dash-card">
						<h3>Types de publications ({dashboard.total_publications})</h3>
						{#if dashboard.doc_types.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<DoughnutChart segments={docTypeSegments} />
						{/if}
					</div>

					<div class="dash-card">
						<h3>Statuts Open Access</h3>
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

	<!-- Tab: Revues -->
	{#if activeTab === 'journals'}
		<div class="tab-content">
			<JournalsListView
				apiKey={`publisher-${publisherId}-journals`}
				externalFilters={{ publisherId }}
				hidePublisherColumn
				withPubs
			/>
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`publisher-${publisherId}-pubs`}
				externalFilters={{ publisherId }}
				basePath={`/publishers/${publisherId}`}
				showFilterBanner={false}
				perPage={50}
			/>
		</div>
	{/if}
{/if}

<style>
	.p-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
	}
	.p-title { font-size: 1.3rem; font-weight: 600; margin: 0 0 10px; }
	.p-meta { display: flex; flex-direction: column; gap: 6px; }
	.meta-row {
		display: flex; align-items: center; gap: 6px;
		flex-wrap: wrap; font-size: 0.95rem;
	}
	.meta-label {
		font-size: 0.8rem; font-weight: 600; color: var(--muted);
		text-transform: uppercase; letter-spacing: 0.3px;
	}
	.id-badge { margin-right: 4px; }
	.type-tag {
		background: var(--border-subtle); color: var(--muted);
		padding: 2px 8px; border-radius: 10px; font-size: 0.85rem;
		margin-right: 8px;
	}

	.tab-content { margin-top: 16px; }
	.loading, .no-results { padding: 20px; color: var(--muted); }

	.dash-grid {
		display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
	}
	@media (max-width: 900px) {
		.dash-grid { grid-template-columns: 1fr; }
	}
	.dash-card-wide { grid-column: 1 / -1; }
	.dash-card {
		background: var(--card); border: 1px solid var(--border);
		border-radius: 6px; padding: 16px;
	}
	.dash-card h3 {
		font-size: 0.95rem; font-weight: 600; margin: 0 0 12px;
	}
	.muted { color: var(--muted); }
</style>
