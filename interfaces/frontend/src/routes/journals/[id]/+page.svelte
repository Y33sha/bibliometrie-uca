<script lang="ts">
	import EntityMetaItem from '#lib/components/EntityMetaItem.svelte';
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api, apiDetail } from '#lib/api/index.js';
	import { issnLabel, serialRelationLabels } from '#lib/labels.js';
	import { issnPortalUrl } from '#lib/utils.js';
	import TabNav from '#lib/components/TabNav.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectsCloud from '#lib/components/SubjectsCloud.svelte';
	import type { components } from '#lib/api/schema.js';

	type SerialDetail = components['schemas']['SerialDetailResponse'];
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
	let subjectList = $state<SubjectFrequency[]>([]);
	let dashboardLoaded = $state(false);

	let showRawDoaj = $state(false);

	let serialTypeLabels: Record<string, string> = $state({});
	let oaModelLabels: Record<string, string> = $state({});

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
		subjectList = await api<SubjectFrequency[]>(`/api/serials/${serialId}/subjects?limit=20`, {
			key: 'j-subjects'
		});
		dashboardLoaded = true;
	}

	function onTabSwitch(tab: string) {
		if (tab === 'dashboard') loadDashboard();
	}

	onMount(async () => {
		const labelMap = (opts: EnumOption[]) => Object.fromEntries(opts.map((o) => [o.value, o.label_fr]));
		const typeLabelsP = api<EnumOption[]>('/api/serials/types').then((opts) => {
			serialTypeLabels = labelMap(opts);
		});
		const oaModelLabelsP = api<EnumOption[]>('/api/serials/oa-models').then((opts) => {
			oaModelLabels = labelMap(opts);
		});
		await Promise.all([loadSerial(), typeLabelsP, oaModelLabelsP]);
		if (activeTab === 'dashboard') loadDashboard();
		await tick();
	});

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		return new Date(iso).toLocaleDateString('fr-FR');
	}
</script>

<svelte:head>
	<title>{pageTitle(journal?.title ?? 'Publication en série')}</title>
</svelte:head>

	<Breadcrumb trail={[{ label: 'Publications en série', path: 'journals' }]} current={journal?.title} />

{#if error}
	<div class="no-results">Publication en série introuvable</div>
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
				<EntityMetaItem label={issnLabel(issn)}><span class="id-badge">{issn.issn}</span></EntityMetaItem>
			{/each}
		</div>
		{#if journal.relations.length}
			<div class="entity-meta">
				{#each journal.relations as relation (`${relation.kind}-${relation.serial_id ?? relation.issn}`)}
					<EntityMetaItem label={serialRelationLabels[relation.kind]}>
						{#if relation.serial_id}
							<a href={resolve(`journals/${relation.serial_id}`)}>{relation.title}</a>
						{:else if relation.issn}
							<a class="id-badge" href={issnPortalUrl(relation.issn)} target="_blank" rel="noopener" title="Portail ISSN (nouvel onglet)">{relation.issn}</a>
						{/if}
					</EntityMetaItem>
				{/each}
			</div>
		{/if}
		<div class="entity-meta">
			{#if journal.publisher_name}
				<EntityMetaItem label="Éditeur">
					{#if journal.publisher_id}
						<a href={resolve(`publishers/${journal.publisher_id}`)} class="publisher-link">{journal.publisher_name}</a>
					{:else}
						<span class="publisher-link">{journal.publisher_name}</span>
					{/if}
				</EntityMetaItem>
			{/if}
			{#if journal.serial_type}
				<EntityMetaItem label="Type">
					<span class="entity-tag">{serialTypeLabels[journal.serial_type] ?? journal.serial_type}</span>
				</EntityMetaItem>
			{/if}
			{#if journal.oa_model}
				<EntityMetaItem label="Open access">
					<span class="entity-tag">{oaModelLabels[journal.oa_model] ?? journal.oa_model}</span>
				</EntityMetaItem>
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
			<PublicationsDashboard
				context={{ kind: 'serial', id: serialId }}
				apiKey="serial-dashboard"
				countries={false}
				oaBreakdown="oa_voie"
			>
				{#snippet subjects()}
					<div class="dash-card">
						<h2>Sujets principaux</h2>
						{#if !dashboardLoaded}
							<div class="loading">Chargement…</div>
						{:else if subjectList.length === 0}
							<p class="muted">Aucun sujet (les sujets génériques sont exclus du top).</p>
						{:else}
							<SubjectsCloud subjects={subjectList} />
						{/if}
					</div>
				{/snippet}
			</PublicationsDashboard>
			{#if journal.doaj_payload}
				<div class="dash-grid doaj-grid">
						<div class="dash-card dash-card-wide">
							<h2>
								Données DOAJ
								{#if journal.doaj_imported_at}
									<span class="muted small">(import {formatDate(journal.doaj_imported_at)})</span>
								{/if}
							</h2>
							<dl class="doaj-fields">
								{#each READABLE_DOAJ_FIELDS as f (f.key)}
									{#if journal.doaj_payload[f.key]}
										<dt>{f.label}</dt>
										<dd>{journal.doaj_payload[f.key]}</dd>
									{/if}
								{/each}
							</dl>
							<button class="toggle-raw" onclick={() => (showRawDoaj = !showRawDoaj)}>
								{showRawDoaj ? 'Masquer' : 'Voir'} le payload DOAJ brut <span class="chevron" class:up={showRawDoaj} aria-hidden="true"></span>
							</button>
							{#if showRawDoaj}
								<pre class="raw-payload">{JSON.stringify(journal.doaj_payload, null, 2)}</pre>
							{/if}
						</div>
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
				context={{ kind: 'serial', id: serialId }}
				basePath={`/journals/${serialId}`}
				perPage={50}
			/>
		</div>
	{/if}
{/if}

<style>

	.loading, .no-results { padding: 20px; color: var(--muted); }
	.doaj-grid { margin-top: 24px; }

	.muted { color: var(--muted); }
	.small { font-size: var(--fs-sm); font-weight: 400; }

	.doaj-fields {
		display: grid; grid-template-columns: max-content 1fr;
		gap: 4px 16px; margin: 0 0 12px;
	}
	.doaj-fields dt { font-weight: 600; color: var(--muted); font-size: var(--fs-sm); }
	.doaj-fields dd { margin: 0; font-size: var(--fs-md); }
	.toggle-raw {
		background: none; border: none; color: var(--accent);
		font-size: var(--fs-sm); cursor: pointer; padding: 4px 0;
	}
	.toggle-raw:hover { text-decoration: underline; }
	.raw-payload {
		background: var(--surface); padding: 12px; border-radius: var(--radius);
		font-size: var(--fs-sm); max-height: 400px; overflow: auto;
		white-space: pre-wrap; word-break: break-word;
	}
</style>
