<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationDrawer from '#lib/components/publications/PublicationDrawer.svelte';
	import SuspectMergesList from './SuspectMergesList.svelte';
	import { api } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';

	// Onglets de la session admin : la liste, puis la file des fusions suspectes.
	let tab = $state('all');
	let suspectMergeCount = $state(0);

	$effect(() => {
		if (!isAdmin()) return;
		void api<{ total: number }>('/api/publications/suspect-merges/count').then(
			(data) => (suspectMergeCount = data.total),
		);
	});

	// Volet de la file des fusions suspectes. La liste ouvre le sien.
	const drawer = useDrawerParam('publication', () => isAdmin() && tab === 'suspect-merges');
</script>

<PageHeader title="Publications" hidden />

{#if isAdmin()}
	<HubTabs
		tabs={[
			{ key: 'all', label: 'Toutes les publications' },
			{ key: 'suspect-merges', label: 'Fusions suspectes', count: suspectMergeCount },
		]}
		active={tab}
		onselect={(key) => (tab = key)}
	/>
{/if}

{#if tab === 'suspect-merges'}
	<SuspectMergesList activePublicationId={drawer.id} onopenPublication={drawer.open} />
{:else}
	<PublicationsListView />
{/if}

{#if drawer.id !== null}
	<PublicationDrawer publicationId={drawer.id} onclose={() => drawer.open(null)} />
{/if}
