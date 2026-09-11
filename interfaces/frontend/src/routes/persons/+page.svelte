<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import PersonsListView from '$lib/components/PersonsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Personnes")}</title>
</svelte:head>

<PersonsListView apiKey="persons-dir" basePath="/persons" />
