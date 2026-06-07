<script lang="ts">
	import PersonsListView from '$lib/components/PersonsListView.svelte';
</script>

<svelte:head>
	<title>Personnes — Bibliométrie UCA</title>
</svelte:head>

<PersonsListView apiKey="persons-dir" basePath="/persons" />
