<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { oaLabelsMap } from '$lib/labels';
	import { docTypeSingular } from '$lib/labels';
	import TabNav from '$lib/components/TabNav.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
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

	// `pub_count` du detail sert au compteur de l'onglet tant que
	// PublicationsListView n'a pas remonté son total post-filtrage.
	let pubsTotal = $state(0);
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
			pubsTotal = journal.pub_count;
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
			{#if journal.is_predatory}
				<span class="badge-predatory" title="Revue prédatrice">Prédatrice</span>
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
			{ id: 'dashboard', label: 'Dashboard', showCount: false },
			{ id: 'publications', label: 'Publications', count: pubsTotal }
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
					<div class="dash-card">
						<h3>Types de documents ({dashboard.total_publications})</h3>
						{#if dashboard.expected_doc_types.length > 0}
							<div class="expected-row">
								<span class="expected-label">Attendus&nbsp;:</span>
								{#each dashboard.expected_doc_types as t (t)}
									<span class="expected-tag">{docTypeSingular[t] ?? t}</span>
								{/each}
							</div>
						{/if}
						{#if dashboard.doc_types.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<table class="count-table">
								<tbody>
									{#each dashboard.doc_types as d (d.doc_type ?? '∅')}
										<tr class:warning={!d.expected}>
											<td>{d.doc_type ? (docTypeSingular[d.doc_type] ?? d.doc_type) : '(non renseigné)'}</td>
											<td class="num">{d.count}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

					<div class="dash-card">
						<h3>Statuts Open Access</h3>
						{#if dashboard.expected_oa_statuses.length > 0}
							<div class="expected-row">
								<span class="expected-label">Attendus&nbsp;:</span>
								{#each dashboard.expected_oa_statuses as s (s)}
									<span class="expected-tag">{oaLabelsMap[s] ?? s}</span>
								{/each}
							</div>
						{/if}
						{#if dashboard.oa_statuses.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<table class="count-table">
								<tbody>
									{#each dashboard.oa_statuses as o (o.oa_status ?? '∅')}
										<tr class:warning={!o.expected}>
											<td>{o.oa_status ? (oaLabelsMap[o.oa_status] ?? o.oa_status) : '(non renseigné)'}</td>
											<td class="num">{o.count}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

					<div class="dash-card dash-card-wide">
						<h3>Sujets dominants</h3>
						{#if subjects.length === 0}
							<p class="muted">Aucun sujet (les sujets génériques sont exclus du top).</p>
						{:else}
							<ul class="subjects-list">
								{#each subjects as s (s.id)}
									<li>
										<a href="{base}/subjects/{s.id}">{s.label}</a>
										<span class="count-pill">{s.count}</span>
									</li>
								{/each}
							</ul>
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
				onTotalChange={(t) => (pubsTotal = t)}
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
	.badge-predatory {
		font-size: 0.7rem; padding: 2px 6px; background: var(--danger);
		color: white; border-radius: 8px; margin-left: 6px;
		vertical-align: middle; font-weight: 600; letter-spacing: 0.3px;
	}

	.tab-content { margin-top: 16px; }
	.loading, .no-results { padding: 20px; color: var(--muted); }

	.dash-grid {
		display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
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

	.count-table { width: 100%; border-collapse: collapse; }
	.count-table td { padding: 6px 8px; font-size: 0.95rem; border-bottom: 1px solid var(--border-subtle); }
	.count-table tr:last-child td { border-bottom: none; }
	.count-table td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
	.count-table tr.warning td { background: #fef3e0; color: #8a4a00; }
	.count-table tr.warning td.num { color: #8a4a00; }

	.expected-row {
		display: flex; align-items: center; flex-wrap: wrap; gap: 4px;
		margin-bottom: 10px; font-size: 0.85rem;
	}
	.expected-label { color: var(--muted); font-weight: 600; margin-right: 4px; }
	.expected-tag {
		background: var(--success-light); color: var(--success);
		padding: 1px 8px; border-radius: 10px; font-size: 0.8rem;
	}

	.subjects-list {
		list-style: none; padding: 0; margin: 0;
		display: flex; flex-wrap: wrap; gap: 8px;
	}
	.subjects-list li {
		display: inline-flex; align-items: center; gap: 6px;
		background: var(--surface); padding: 4px 10px; border-radius: 12px;
		font-size: 0.9rem;
	}
	.subjects-list a { color: var(--accent); text-decoration: none; }
	.subjects-list a:hover { text-decoration: underline; }
	.count-pill {
		background: #fff; padding: 0 6px; border-radius: 8px;
		font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums;
	}

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
