<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import MonographsListView from '$lib/components/MonographsListView.svelte';
</script>

<svelte:head><title>{pageTitle('Monographies')}</title></svelte:head>

<h2>Monographies</h2>

<MonographsListView apiKey="admin-monographs" urlSync basePath="/admin/monographs" />
