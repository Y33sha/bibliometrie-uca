<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api } from '$lib/api';
	import { typeLabels, oaLabelsMap } from '$lib/labels';
	import TabNav from '$lib/components/TabNav.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { components } from '$lib/api/schema';

	type PublisherDetail = components['schemas']['PublisherDetailResponse'];
	type PublisherDashboard = components['schemas']['PublisherDashboardResponse'];
	type SubjectFrequency = components['schemas']['SubjectFrequency'];
	type JournalListResponse = components['schemas']['JournalListResponse'];
	type Journal = components['schemas']['JournalOut'];
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

	let dashboard = $state<PublisherDashboard | null>(null);
	let subjects = $state<SubjectFrequency[]>([]);
	let dashboardLoaded = $state(false);

	// `pub_count` du detail sert au compteur de l'onglet tant que
	// PublicationsListView n'a pas remonté son total post-filtrage.
	let pubsTotal = $state(0);

	// Onglet Revues : tableau paginé des revues de l'éditeur.
	let journals = $state<Journal[]>([]);
	let journalsTotal = $state(0);
	let journalsPage = $state(1);
	let journalsPages = $state(1);
	let journalsLoaded = $state(false);
	const JOURNALS_PER_PAGE = 50;

	// Labels FR des publisher_type, alimentés par /api/publisher-types.
	let publisherTypeLabels: Record<string, string> = $state({});

	async function loadPublisher() {
		try {
			publisher = await api<PublisherDetail>(`/api/publishers/${publisherId}`);
			pubsTotal = publisher.pub_count;
		} catch {
			error = true;
		}
	}

	async function loadPublisherTypeLabels() {
		const opts = await api<EnumOption[]>('/api/publisher-types');
		publisherTypeLabels = Object.fromEntries(opts.map((o) => [o.value, o.label_fr]));
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

	async function loadJournals() {
		const params = new URLSearchParams();
		params.set('publisher_id', String(publisherId));
		params.set('with_pubs', 'true');
		params.set('sort', '-pubs');
		params.set('page', String(journalsPage));
		params.set('per_page', String(JOURNALS_PER_PAGE));
		const resp = await api<JournalListResponse>(`/api/journals?${params}`, {
			key: 'p-journals'
		});
		journals = resp.journals;
		journalsTotal = resp.total;
		journalsPages = resp.pages;
		journalsLoaded = true;
	}

	function onTabSwitch(tab: string) {
		if (tab === 'dashboard') loadDashboard();
		if (tab === 'journals' && !journalsLoaded) loadJournals();
	}

	onMount(async () => {
		await Promise.all([loadPublisher(), loadPublisherTypeLabels()]);
		if (activeTab === 'dashboard') loadDashboard();
		if (activeTab === 'journals') loadJournals();
		await tick();
	});

	function formatJournalIssns(j: Journal): string {
		const parts: string[] = [];
		if (j.issn) parts.push(j.issn);
		if (j.eissn) parts.push(j.eissn);
		return parts.join(' / ');
	}
</script>

<svelte:head>
	<title>{publisher?.name ?? 'Éditeur'} — Bibliométrie UCA</title>
</svelte:head>

{#if error}
	<div class="no-results">Éditeur introuvable</div>
{:else if !publisher}
	<div class="loading">Chargement…</div>
{:else}
	<!-- Header -->
	<div class="p-header">
		<h1 class="p-title">
			{publisher.name}
			{#if publisher.is_predatory}
				<span class="badge-predatory" title="Éditeur prédateur">Prédateur</span>
			{/if}
		</h1>
		<div class="p-meta">
			<div class="meta-row">
				<span class="meta-label">Type</span>
				<span class="type-tag">
					{publisherTypeLabels[publisher.publisher_type] ?? publisher.publisher_type}
				</span>
				{#if publisher.country}
					<span class="meta-label">Pays</span>
					<span class="type-tag">{publisher.country}</span>
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
			{ id: 'dashboard', label: 'Dashboard', showCount: false },
			{ id: 'journals', label: 'Revues', count: journalsLoaded ? journalsTotal : publisher.journal_count },
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
						<h3>Types de revues ({publisher.journal_count})</h3>
						{#if dashboard.journal_types.length === 0}
							<p class="muted">Aucune revue rattachée.</p>
						{:else}
							<table class="count-table">
								<tbody>
									{#each dashboard.journal_types as j (j.journal_type ?? '∅')}
										<tr>
											<td>{j.journal_type ?? '(non renseigné)'}</td>
											<td class="num">{j.count}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

					<div class="dash-card">
						<h3>Types de publications ({dashboard.total_publications})</h3>
						{#if dashboard.doc_types.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<table class="count-table">
								<tbody>
									{#each dashboard.doc_types as d (d.doc_type ?? '∅')}
										<tr>
											<td>{d.doc_type ? (typeLabels[d.doc_type] ?? d.doc_type) : '(non renseigné)'}</td>
											<td class="num">{d.count}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{/if}
					</div>

					<div class="dash-card dash-card-wide">
						<h3>Statuts Open Access</h3>
						{#if dashboard.oa_statuses.length === 0}
							<p class="muted">Aucune publication rattachée.</p>
						{:else}
							<table class="count-table">
								<tbody>
									{#each dashboard.oa_statuses as o (o.oa_status ?? '∅')}
										<tr>
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
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Revues -->
	{#if activeTab === 'journals'}
		<div class="tab-content">
			{#if !journalsLoaded}
				<div class="loading">Chargement…</div>
			{:else}
				<table class="journals-table">
					<thead>
						<tr>
							<th>Titre</th>
							<th>ISSN</th>
							<th>Type</th>
							<th class="num">Publis</th>
						</tr>
					</thead>
					<tbody>
						{#each journals as j (j.id)}
							<tr>
								<td>
									<a href="{base}/journals/{j.id}" class="journal-link">{j.title}</a>
									{#if j.is_in_doaj}<span class="badge-doaj">DOAJ</span>{/if}
								</td>
								<td class="issn-cell">{formatJournalIssns(j)}</td>
								<td class="muted">{j.journal_type ?? ''}</td>
								<td class="num">{j.pub_count.toLocaleString('fr-FR')}</td>
							</tr>
						{/each}
						{#if journals.length === 0}
							<tr><td colspan="4" class="no-results">Aucune revue rattachée à cet éditeur.</td></tr>
						{/if}
					</tbody>
				</table>
				<Pagination
					page={journalsPage}
					pages={journalsPages}
					onchange={(p) => { journalsPage = p; loadJournals(); }}
				/>
			{/if}
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
				onTotalChange={(t) => (pubsTotal = t)}
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
		background: #f0efec; color: var(--muted);
		padding: 2px 8px; border-radius: 10px; font-size: 0.85rem;
		margin-right: 8px;
	}
	.badge-predatory {
		font-size: 0.7rem; padding: 2px 6px; background: #c0392b;
		color: white; border-radius: 8px; margin-left: 8px;
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

	.count-table { width: 100%; border-collapse: collapse; }
	.count-table td { padding: 6px 8px; font-size: 0.95rem; border-bottom: 1px solid #f0efec; }
	.count-table tr:last-child td { border-bottom: none; }
	.count-table td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }

	.subjects-list {
		list-style: none; padding: 0; margin: 0;
		display: flex; flex-wrap: wrap; gap: 8px;
	}
	.subjects-list li {
		display: inline-flex; align-items: center; gap: 6px;
		background: #f5f4f1; padding: 4px 10px; border-radius: 12px;
		font-size: 0.9rem;
	}
	.subjects-list a { color: var(--accent); text-decoration: none; }
	.subjects-list a:hover { text-decoration: underline; }
	.count-pill {
		background: #fff; padding: 0 6px; border-radius: 8px;
		font-size: 0.8rem; color: var(--muted); font-variant-numeric: tabular-nums;
	}

	.journals-table {
		width: 100%; border-collapse: collapse;
		background: var(--card); border: 1px solid var(--border); border-radius: 6px;
	}
	.journals-table thead th {
		background: #f5f4f1; padding: 8px 10px; text-align: left;
		font-size: 0.85rem; font-weight: 600; color: var(--muted);
		border-bottom: 2px solid var(--border); white-space: nowrap;
	}
	.journals-table thead th.num { text-align: right; }
	.journals-table tbody tr { border-bottom: 1px solid #f0efec; }
	.journals-table tbody tr:last-child { border-bottom: none; }
	.journals-table tbody tr:hover { background: #fafaf8; }
	.journals-table td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }
	.journals-table td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
	.issn-cell { color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; white-space: nowrap; }

	.journal-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.journal-link:hover { text-decoration: underline; }
	.badge-doaj {
		font-size: 0.7rem; padding: 1px 5px; background: #2e7d32;
		color: white; border-radius: 8px; margin-left: 6px;
		vertical-align: middle; font-weight: 600;
	}
</style>
