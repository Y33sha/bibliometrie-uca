<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import PublicationsListView from '$lib/components/PublicationsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Publications")}</title>
</svelte:head>

<PublicationsListView restrictToPublications />
