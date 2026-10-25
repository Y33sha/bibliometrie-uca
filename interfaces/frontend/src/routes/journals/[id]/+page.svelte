<script lang="ts">
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api, apiDetail } from '#lib/api/index.js';
	import { oaLabelsMap } from '#lib/labels.js';
	import { docTypeSingular, issnLabel } from '#lib/labels.js';
	import TabNav from '#lib/components/TabNav.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
	import DoughnutChart from '#lib/components/charts/DoughnutChart.svelte';
	import { oaStatusColor } from '#lib/components/charts/cssColor.js';
	import SubjectsCloud from '#lib/components/SubjectsCloud.svelte';
	import type { components } from '#lib/api/schema.js';

	type SerialDetail = components['schemas']['SerialDetailResponse'];
	type SerialDashboard = components['schemas']['SerialDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	type EnumOption = components['schemas']['EnumOption'];

	const serialId = $derived(Number(page.params.id));
	const activeTab = $derived(
		(() => {
			const t = page.url.searchParams.get('tab');
			return t === 'publications' || t === 'monographs' ? t : 'dashboard';
		})()
	);

	let journal = $state<SerialDetail | null>(null);

	// Onglet des monographies, selon le type de la revue : volumes d'une série d'actes, livres d'une collection.
	const MONOGRAPHS_TAB_LABELS: Record<string, string> = { proceedings: 'Volumes', book_series: 'Livres' };
	const monographsTabLabel = $derived(journal?.serial_type ? MONOGRAPHS_TAB_LABELS[journal.serial_type] : undefined);
	let error = $state(false);
	let canGoBack = $state(false);

	let dashboard = $state<SerialDashboard | null>(null);
	let subjects = $state<SubjectFrequency[]>([]);
	let dashboardLoaded = $state(false);

	// Distributions en segments pour les doughnuts ; `expected=false` (valeur inattendue pour le type de revue / modèle OA) est signalé visuellement par le composant (couleur d'alerte + ⚠ en légende), sans énumérer les valeurs attendues.
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

	let serialTypeLabels: Record<string, string> = $state({});

	// Sélection des champs DOAJ « lisibles ». Le payload complet est exposé via le toggle (« Voir payload brut ») pour permettre l'exploration au-delà de cette sélection.
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

	async function loadSerial() {
		try {
			journal = await apiDetail<SerialDetail>(`/api/serials/${serialId}`);
		} catch {
			error = true;
		}
	}

	async function loadDashboard() {
		if (dashboardLoaded) return;
		const [d, s] = await Promise.all([
			api<SerialDashboard>(`/api/serials/${serialId}/dashboard`, { key: 'j-dashboard' }),
			api<SubjectFrequency[]>(`/api/serials/${serialId}/subjects?limit=20`, {
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
		const labelsP = api<EnumOption[]>('/api/serials/types').then((opts) => {
			serialTypeLabels = Object.fromEntries(opts.map((o) => [o.value, o.label_fr]));
		});
		await Promise.all([loadSerial(), labelsP]);
		if (activeTab === 'dashboard') loadDashboard();
		await tick();
	});

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		return new Date(iso).toLocaleDateString('fr-FR');
	}
</script>

<svelte:head>
	<title>{pageTitle(journal?.title ?? 'Revue')}</title>
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
	<div class="entity-header">
		<h1 class="entity-title">
			{journal.title}
			{#if journal.is_in_doaj}
				{#if journal.doaj_url}
					<a class="badge-doaj" href={journal.doaj_url} target="_blank" rel="noopener" title="Fiche DOAJ (nouvel onglet)">DOAJ</a>
				{:else}
					<span class="badge-doaj" title="Indexée dans DOAJ">DOAJ</span>
				{/if}
			{/if}
		</h1>
		<div class="entity-meta">
			{#each journal.issn_details.filter((i) => i.status === 'active' || i.linking) as issn (issn.issn)}
				<span class="entity-meta-label">{issnLabel(issn)}</span>
				<span class="id-badge">{issn.issn}</span>
			{/each}
		</div>
		<div class="entity-meta">
			{#if journal.publisher_name}
				<span class="entity-meta-label">Éditeur</span>
				{#if journal.publisher_id}
					<a href={resolve(`publishers/${journal.publisher_id}`)} class="publisher-link">{journal.publisher_name}</a>
				{:else}
					<span class="publisher-link">{journal.publisher_name}</span>
				{/if}
			{/if}
			{#if journal.serial_type}
				<span class="entity-meta-label">Type</span>
				<span class="entity-tag">{serialTypeLabels[journal.serial_type] ?? journal.serial_type}</span>
			{/if}
			{#if journal.oa_model}
				<span class="entity-meta-label">OA</span>
				<span class="entity-tag">{journal.oa_model}</span>
			{/if}
			{#if journal.apc_amount != null}
				<span class="entity-meta-label">APC</span>
				<span class="entity-tag">
					{journal.apc_amount} {journal.apc_currency ?? ''}
				</span>
			{/if}
		</div>
	</div>

	<!-- Tabs -->
	<TabNav
		tabs={[
			{ id: 'dashboard', label: 'Dashboard' },
			...(monographsTabLabel ? [{ id: 'monographs', label: monographsTabLabel }] : []),
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

	<!-- Tab: Monographies -->
	{#if activeTab === 'monographs' && monographsTabLabel}
		<div class="tab-content">
			<MonographsListView apiKey={`journal-${serialId}-monographs`} externalFilters={{ serialId }} />
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`journal-${serialId}-publications`}
				externalFilters={{ serialId }}
				basePath={`/journals/${serialId}`}
				showFilterBanner={false}
				perPage={50}
			/>
		</div>
	{/if}
{/if}

<style>

	.loading, .no-results { padding: 20px; color: var(--muted); }

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
		background: var(--surface); padding: 12px; border-radius: var(--radius);
		font-size: 0.8rem; max-height: 400px; overflow: auto;
		white-space: pre-wrap; word-break: break-word;
	}
</style>
