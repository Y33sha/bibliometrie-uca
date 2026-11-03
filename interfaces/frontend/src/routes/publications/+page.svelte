<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import SuspectMergesList from './SuspectMergesList.svelte';
	import { api } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { useTabParam } from '#lib/composables/useTabParam.svelte.js';

	// Onglets de la session admin : la liste, puis la file des fusions suspectes. L'onglet ouvert se garde dans l'URL (`?tab=`).
	const tab = useTabParam(['suspect-merges'], isAdmin);
	let suspectMergeCount = $state(0);

	// Une fusion de publications fait entrer ou sortir des publications de la file des fusions suspectes.
	function loadSuspectMergeCount() {
		void api<{ total: number }>('/api/publications/suspect-merges/count').then(
			(data) => (suspectMergeCount = data.total),
		);
	}

	$effect(() => {
		if (isAdmin()) loadSuspectMergeCount();
	});
</script>

<PageHeader title="Publications" hidden />

{#if isAdmin()}
	<HubTabs
		tabs={[
			{ key: 'all', label: 'Toutes les publications' },
			{ key: 'suspect-merges', label: 'Fusions suspectes', count: suspectMergeCount },
		]}
		active={tab.current}
		onselect={(key) => tab.select(key as 'all' | 'suspect-merges')}
	/>
{/if}

{#if tab.current === 'suspect-merges'}
	<SuspectMergesList onchange={loadSuspectMergeCount} />
{:else}
	<PublicationsListView onchange={loadSuspectMergeCount} />
{/if}
