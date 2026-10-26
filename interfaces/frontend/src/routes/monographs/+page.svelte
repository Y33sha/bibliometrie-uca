<script lang="ts">
	import { pageTitle } from '#lib/institution.svelte.js';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Monographies")}</title>
</svelte:head>

<h1 class="visually-hidden">Monographies</h1>

<MonographsListView apiKey="monographs-list" urlSync />
