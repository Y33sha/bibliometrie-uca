<script lang="ts">
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
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
	import IdentifierLink from '#lib/components/IdentifierLink.svelte';
	import { countryName } from '#lib/countryNames.js';
	import { crossrefMemberIds } from '#lib/sources.svelte.js';
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
	// Un type inconnu ne dit rien au visiteur : l'en-tête l'omet.
	const knownType = $derived(publisher !== null && publisher.publisher_type !== 'unknown');

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

<EntityBreadcrumb section={{ label: 'Éditeurs', path: 'publishers' }} name={publisher?.name} fallback="Éditeur" />

{#if error || !publisher}
	<EntityStatus {error} notFound="Éditeur introuvable" />
{:else}
	<!-- Header -->
	<div class="entity-header">
		<TitleRow onopen={isAdmin() ? () => drawer.open(publisherId) : undefined}>
			<h1 class="entity-title">{publisher.name}</h1>
			{#snippet identifierLinks()}
				{#if publisher!.openalex_id}<IdentifierLink id_type="openalex" id_value={publisher!.openalex_id} />{/if}
				{#each crossrefMemberIds(publisher!.doi_prefixes) as member (member)}<IdentifierLink id_type="crossref_member" id_value={String(member)} />{/each}
			{/snippet}
		</TitleRow>
		{#if knownType || publisher.country}
			<div class="entity-meta">
				{#if knownType}<span>{publisherTypeLabels[publisher.publisher_type] ?? publisher.publisher_type}</span>{/if}
				{#if publisher.country}<span>{countryName(publisher.country) ?? publisher.country.toUpperCase()}</span>{/if}
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

</style>
