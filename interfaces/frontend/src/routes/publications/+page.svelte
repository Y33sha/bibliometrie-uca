<script lang="ts">
	import { page } from '$app/state';
	import { setQueryParam } from '#lib/url.js';
	import { pageTitle } from '#lib/institution.svelte.js';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationDrawer from './PublicationDrawer.svelte';
	import SuspectMergesList from './SuspectMergesList.svelte';
	import { api } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';

	// Onglets de la session admin : la liste, puis la file des fusions suspectes.
	let tab = $state('all');
	let suspectMergeCount = $state(0);

	$effect(() => {
		if (!isAdmin()) return;
		void api<{ total: number }>('/api/publications/suspect-merges/count').then(
			(data) => (suspectMergeCount = data.total),
		);
	});

	// Volet d'une publication, réservé à la session admin : ouvert tant que `?publication=<id>` figure dans l'URL.
	const selectedPublicationId = $derived(
		isAdmin() ? Number(page.url.searchParams.get('publication')) || null : null,
	);

	function selectPublication(id: number | null) {
		void setQueryParam('publication', id === null ? null : String(id));
	}
</script>

<svelte:head>
	<title>{pageTitle("Publications")}</title>
</svelte:head>

<h1 class="visually-hidden">Publications</h1>

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
	<SuspectMergesList
		activePublicationId={selectedPublicationId}
		onopenPublication={selectPublication}
	/>
{:else}
	<PublicationsListView
		restrictToPublications
		activePublicationId={selectedPublicationId}
		onopenPublication={isAdmin() ? selectPublication : undefined}
	/>
{/if}

{#if selectedPublicationId !== null}
	<PublicationDrawer
		publicationId={selectedPublicationId}
		onclose={() => selectPublication(null)}
	/>
{/if}
