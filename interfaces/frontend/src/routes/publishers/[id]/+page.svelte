<script lang="ts">
	import EntityMetaItem from '#lib/components/EntityMetaItem.svelte';
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import { api, apiDetail } from '#lib/api/index.js';
	import TabNav from '#lib/components/TabNav.svelte';
	import { activeTabId, type TabDef } from '#lib/tabs.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import SerialsListView from '#lib/components/SerialsListView.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectsCard from '#lib/components/SubjectsCard.svelte';
	import TitleRow from '#lib/components/TitleRow.svelte';
	import PublisherDrawer from '#lib/components/publishers/PublisherDrawer.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import type { components } from '#lib/api/schema.js';

	type PublisherDetail = components['schemas']['Publisher'];
	type EnumOption = components['schemas']['EnumOption'];

	const publisherId = $derived(Number(page.params.id));

	// Volet d'édition de l'éditeur, en session admin : ouvert tant que `?publisher=<id>` figure dans l'URL.
	const drawer = useDrawerParam('publisher', isAdmin);

	const tabs: TabDef[] = [
		{ id: 'dashboard', label: 'Dashboard' },
		{ id: 'serials', label: 'Publications en série' },
		{ id: 'monographs', label: 'Monographies' },
		{ id: 'publications', label: 'Publications' },
	];
	const activeTab = $derived(activeTabId(tabs, page.url.searchParams));

	let publisher = $state<PublisherDetail | null>(null);
	let error = $state(false);

	// Label FR du publisher_type, affiché dans l'en-tête de la page.
	let publisherTypeLabels: Record<string, string> = $state({});

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

	onMount(async () => {
		await Promise.all([loadPublisher(), loadTypeLabels()]);
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
		<TitleRow onopen={isAdmin() ? () => drawer.open(publisherId) : undefined}>
			<h1 class="entity-title">
				{publisher.name}
			</h1>
		</TitleRow>
		<div class="entity-meta">
			<EntityMetaItem label="Type">
				<span class="tag">
					{publisherTypeLabels[publisher.publisher_type] ?? publisher.publisher_type}
				</span>
			</EntityMetaItem>
			{#if publisher.country}
				<EntityMetaItem label="Pays"><span class="tag">{publisher.country.toUpperCase()}</span></EntityMetaItem>
			{/if}
			{#if publisher.openalex_id}
				<EntityMetaItem label="OpenAlex"><span class="tag id-badge">{publisher.openalex_id}</span></EntityMetaItem>
			{/if}
		</div>
		{#if publisher.doi_prefixes.length > 0}
			<div class="entity-meta">
				<EntityMetaItem label="Préfixes DOI">
					{#each publisher.doi_prefixes as p (p.prefix)}
						<span class="tag id-badge" title="RA: {p.ra}">{p.prefix}</span>
					{/each}
				</EntityMetaItem>
			</div>
		{/if}
	</div>

	<!-- Tabs -->
	<TabNav {tabs} />

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			<PublicationsDashboard
				context={{ kind: 'publisher', id: publisherId }}
				apiKey="publisher-dashboard"
				countries={false}
				oaBreakdown="oa_voie"
			>
				{#snippet subjects()}
					<SubjectsCard endpoint="/api/publishers/{publisherId}/subjects" />
				{/snippet}
			</PublicationsDashboard>
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

{#if drawer.id !== null}
	<PublisherDrawer id={drawer.id} onclose={() => drawer.open(null)} onchange={loadPublisher} />
{/if}

<style>

	.loading, .no-results { padding: 20px; color: var(--muted); }
</style>
