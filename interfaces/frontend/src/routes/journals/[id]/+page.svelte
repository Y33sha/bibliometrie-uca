<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { oaLabelsMap } from '$lib/labels';
	import { docTypeSingular } from '$lib/labels';
	import TabNav from '$lib/components/TabNav.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
	import DoughnutChart from '$lib/components/charts/DoughnutChart.svelte';
	import { oaStatusColor } from '$lib/components/charts/oaColors';
	import SubjectsCloud from '$lib/components/SubjectsCloud.svelte';
	import type { components } from '$lib/api/schema';

	type JournalDetail = components['schemas']['JournalDetailResponse'];
	type JournalDashboard = components['schemas']['JournalDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	type EnumOption = components['schemas']['EnumOption'];

	const journalId = $derived(Number($page.params.id));
	const activeTab = $derived(
		$page.url.searchParams.get('tab') === 'publications' ? 'publications' : 'dashboard'
	);

	let journal = $state<JournalDetail | null>(null);
	let error = $state(false);
	let canGoBack = $state(false);

	let dashboard = $state<JournalDashboard | null>(null);
	let subjects = $state<SubjectFrequency[]>([]);
	let dashboardLoaded = $state(false);

	// Distributions en segments pour les doughnuts ; `expected=false` (valeur
	// inattendue pour le type de revue / modèle OA) est signalé visuellement
	// par le composant (couleur d'alerte + ⚠ en légende), sans énumérer les
	// valeurs attendues.
	const docTypeSegments = $derived(
		(dashboard?.doc_types ?? []).map((d) => ({
			label: d.doc_type ? (docTypeSingular[d.doc_type] ?? d.doc_type) : '(non renseigné)',
			value: d.count,
			expected: d.expected
		}))
	);
	const oaStatusSegments = $derived(
		(dashboard?.oa_statuses ?? []).map((o) => ({
			label: o.oa_status ? (oaLabelsMap[o.oa_status] ?? o.oa_status) : '(non renseigné)',
			value: o.count,
			color: oaStatusColor(o.oa_status),
			expected: o.expected
		}))
	);

	let showRawDoaj = $state(false);

	let journalTypeLabels: Record<string, string> = $state({});

	// Sélection des champs DOAJ « lisibles ». Le payload complet est exposé
	// via le toggle (« Voir payload brut ») pour permettre l'exploration
	// au-delà de cette sélection.
	const READABLE_DOAJ_FIELDS: { key: string; label: string }[] = [
		{ key: 'Journal license', label: 'Licence' },
		{ key: 'Country of publisher', label: 'Pays' },
		{ key: 'Publisher', label: 'Éditeur (DOAJ)' },
		{ key: 'Languages in which the journal accepts manuscripts', label: 'Langues' },
		{ key: 'Subjects', label: 'Sujets (DOAJ)' },
		{ key: 'When did the journal start to publish all content using an open license?', label: 'OA depuis' },
		{ key: 'Journal article processing charges (APCs)', label: 'APC' },
		{ key: 'APC amount', label: 'Montant APC' },
		{ key: 'APC currency', label: 'Devise APC' }
	];

	async function loadJournal() {
		try {
			journal = await api<JournalDetail>(`/api/journals/${journalId}`);
		} catch {
			error = true;
		}
	}

	async function loadDashboard() {
		if (dashboardLoaded) return;
		const [d, s] = await Promise.all([
			api<JournalDashboard>(`/api/journals/${journalId}/dashboard`, { key: 'j-dashboard' }),
			api<SubjectFrequency[]>(`/api/journals/${journalId}/subjects?limit=20`, {
				key: 'j-subjects'
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
		const labelsP = api<EnumOption[]>('/api/journal-types').then((opts) => {
			journalTypeLabels = Object.fromEntries(opts.map((o) => [o.value, o.label_fr]));
		});
		await Promise.all([loadJournal(), labelsP]);
		if (activeTab === 'dashboard') loadDashboard();
		await tick();
	});

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		return new Date(iso).toLocaleDateString('fr-FR');
	}
</script>

<svelte:head>
	<title>{journal?.title ?? 'Revue'} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
	<!-- svelte-ignore a11y_invalid_attribute -->
	<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

{#if error}
	<div class="no-results">Revue introuvable</div>
{:else if !journal}
	<div class="loading">Chargement…</div>
{:else}
	<!-- Header -->
	<div class="j-header">
		<h1 class="j-title">
			{journal.title}
			{#if journal.is_in_doaj}
				{#if journal.doaj_url}
					<a class="badge-doaj" href={journal.doaj_url} target="_blank" rel="noopener" title="Fiche DOAJ (nouvel onglet)">DOAJ</a>
				{:else}
					<span class="badge-doaj" title="Indexée dans DOAJ">DOAJ</span>
				{/if}
			{/if}
		</h1>
		<div class="j-meta">
			<div class="meta-row">
				{#if journal.issn}
					<span class="meta-label">ISSN</span>
					<span class="id-badge">{journal.issn}</span>
				{/if}
				{#if journal.eissn}
					<span class="meta-label">eISSN</span>
					<span class="id-badge">{journal.eissn}</span>
				{/if}
				{#if journal.issnl}
					<span class="meta-label">ISSN-L</span>
					<span class="id-badge">{journal.issnl}</span>
				{/if}
				{#if journal.doi_prefix}
					<span class="meta-label">DOI préfixe</span>
					<span class="id-badge">{journal.doi_prefix}</span>
				{/if}
			</div>
			<div class="meta-row">
				{#if journal.pub_name}
					<span class="meta-label">Éditeur</span>
					{#if journal.publisher_id}
						<a href="{base}/publishers/{journal.publisher_id}" class="publisher-link">{journal.pub_name}</a>
					{:else}
						<span class="publisher-link">{journal.pub_name}</span>
					{/if}
				{/if}
				{#if journal.journal_type}
					<span class="meta-label">Type</span>
					<span class="type-tag">{journalTypeLabels[journal.journal_type] ?? journal.journal_type}</span>
				{/if}
				{#if journal.oa_model}
					<span class="meta-label">OA</span>
					<span class="type-tag">{journal.oa_model}</span>
				{/if}
				{#if journal.apc_amount != null}
					<span class="meta-label">APC</span>
					<span class="type-tag">
						{journal.apc_amount} {journal.apc_currency ?? ''}
					</span>
				{/if}
			</div>
		</div>
	</div>

	<!-- Tabs -->
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard' },
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
						<h3>Types de documents ({dashboard.total_publications})</h3>
						{#if dashboard.doc_types.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<DoughnutChart segments={docTypeSegments} flagAnomalies />
						{/if}
					</div>

					<div class="dash-card">
						<h3>Statuts Open Access</h3>
						{#if dashboard.oa_statuses.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<DoughnutChart segments={oaStatusSegments} flagAnomalies />
						{/if}
					</div>

					{#if journal.doaj_payload}
						<div class="dash-card dash-card-wide">
							<h3>
								Données DOAJ
								{#if journal.doaj_imported_at}
									<span class="muted small">(import {formatDate(journal.doaj_imported_at)})</span>
								{/if}
							</h3>
							<dl class="doaj-fields">
								{#each READABLE_DOAJ_FIELDS as f (f.key)}
									{#if journal.doaj_payload[f.key]}
										<dt>{f.label}</dt>
										<dd>{journal.doaj_payload[f.key]}</dd>
									{/if}
								{/each}
							</dl>
							<button class="toggle-raw" onclick={() => (showRawDoaj = !showRawDoaj)}>
								{showRawDoaj ? '▾ Masquer' : '▸ Voir'} le payload DOAJ brut
							</button>
							{#if showRawDoaj}
								<pre class="raw-payload">{JSON.stringify(journal.doaj_payload, null, 2)}</pre>
							{/if}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`journal-${journalId}-pubs`}
				externalFilters={{ journalId }}
				basePath={`/journals/${journalId}`}
				showFilterBanner={false}
				perPage={50}
			/>
		</div>
	{/if}
{/if}

<style>
	.j-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
	}
	.j-title { font-size: 1.3rem; font-weight: 600; margin: 0 0 10px; }
	.j-meta { display: flex; flex-direction: column; gap: 6px; }
	.meta-row {
		display: flex; align-items: center; gap: 6px;
		flex-wrap: wrap; font-size: 0.95rem;
	}
	.meta-label {
		font-size: 0.8rem; font-weight: 600; color: var(--muted);
		text-transform: uppercase; letter-spacing: 0.3px;
	}
	.id-badge { margin-right: 8px; }
	.publisher-link {
		color: var(--muted); font-size: 0.95rem; text-decoration: none;
	}
	a.publisher-link:hover { text-decoration: underline; }
	.type-tag {
		background: var(--border-subtle); color: var(--muted);
		padding: 2px 8px; border-radius: 10px; font-size: 0.85rem;
	}
	.badge-doaj {
		font-size: 0.7rem; padding: 2px 6px; background: var(--success);
		color: white; border-radius: 8px; margin-left: 8px;
		vertical-align: middle; font-weight: 600; letter-spacing: 0.3px;
		text-decoration: none;
	}
	a.badge-doaj:hover { background: #256528; }

	.tab-content { margin-top: 16px; }
	.loading, .no-results { padding: 20px; color: var(--muted); }

	.dash-grid {
		display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
	}
	@media (max-width: 760px) {
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
	.small { font-size: 0.8rem; font-weight: 400; }

	.doaj-fields {
		display: grid; grid-template-columns: max-content 1fr;
		gap: 4px 16px; margin: 0 0 12px;
	}
	.doaj-fields dt { font-weight: 600; color: var(--muted); font-size: 0.85rem; }
	.doaj-fields dd { margin: 0; font-size: 0.9rem; }
	.toggle-raw {
		background: none; border: none; color: var(--accent);
		font-size: 0.85rem; cursor: pointer; padding: 4px 0;
	}
	.toggle-raw:hover { text-decoration: underline; }
	.raw-payload {
		background: var(--surface); padding: 12px; border-radius: 4px;
		font-size: 0.8rem; max-height: 400px; overflow: auto;
		white-space: pre-wrap; word-break: break-word;
	}
</style>
