<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/index.js';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import SerialsListView from '#lib/components/SerialsListView.svelte';
	import SerialDuplicatesList from './SerialDuplicatesList.svelte';
	import LikelyProceedingsList from './LikelyProceedingsList.svelte';
	import DoiNamespaceConflictsList from './DoiNamespaceConflictsList.svelte';
	import { isAdmin } from '#lib/session.svelte.js';
	import { useTabParam } from '#lib/composables/useTabParam.svelte.js';

	// Onglets de la session admin : la liste, une file par type de doublon potentiel, la file des recueils d'actes probables, puis celle des publications en série que contredit l'espace de noms DOI. L'onglet ouvert se garde dans l'URL (`?tab=`).
	type TabKey = 'all' | 'same-titles' | 'likely-proceedings' | 'doi-namespace-conflicts';
	const QUEUES: TabKey[] = ['same-titles', 'likely-proceedings', 'doi-namespace-conflicts'];
	const tab = useTabParam(QUEUES, isAdmin);
	let sameTitleCount = $state(0);
	let likelyProceedingsCount = $state(0);
	let doiNamespaceConflictsCount = $state(0);

	async function queueCount(queue: Exclude<TabKey, 'all'>): Promise<number> {
		try {
			return (await api<{ total: number }>(`/api/serials/${queue}/count`)).total;
		} catch {
			return 0;
		}
	}

	// Une modification de titre ou de type, ou une fusion, fait entrer ou sortir des publications en série des files.
	async function loadQueueCounts() {
		[sameTitleCount, likelyProceedingsCount, doiNamespaceConflictsCount] = await Promise.all([
			queueCount('same-titles'),
			queueCount('likely-proceedings'),
			queueCount('doi-namespace-conflicts'),
		]);
	}

	onMount(() => {
		if (isAdmin()) loadQueueCounts();
	});
</script>

<PageHeader title="Publications en série" hidden />

{#if isAdmin()}
	<HubTabs
		tabs={[
			{ key: 'all', label: 'Toutes les publications en série' },
			{ key: 'same-titles', label: 'Titres identiques', count: sameTitleCount },
			{ key: 'likely-proceedings', label: "Recueils d'actes probables", count: likelyProceedingsCount },
			{ key: 'doi-namespace-conflicts', label: 'Contredites par le DOI', count: doiNamespaceConflictsCount },
		]}
		active={tab.current}
		onselect={(key) => tab.select(key as TabKey)}
	/>
{/if}

{#if tab.current === 'same-titles'}
	<SerialDuplicatesList
		url="/api/serials/same-titles"
		intro="Deux publications en série de même titre qui ont chacune un ISSN sont des homonymes probables : elles n'apparaissent pas ici."
		onchange={loadQueueCounts}
	/>
{:else if tab.current === 'likely-proceedings'}
	<LikelyProceedingsList onchange={loadQueueCounts} />
{:else if tab.current === 'doi-namespace-conflicts'}
	<DoiNamespaceConflictsList onchange={loadQueueCounts} />
{:else}
	<SerialsListView urlSync onchange={loadQueueCounts} />
{/if}
