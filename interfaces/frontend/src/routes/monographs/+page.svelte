<script lang="ts">
	import { institution, pageTitle } from '$lib/institution.svelte';
	import MonographsListView from '$lib/components/MonographsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Monographies")}</title>
</svelte:head>

<h1>Monographies</h1>
<p class="hint">Livres et volumes d'actes contenant des publications du périmètre {institution.name}.</p>

<MonographsListView apiKey="monographs-list" basePath="/monographs" />

<style>
	h1 { margin: 0 0 8px; font-size: 1.5rem; }
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }
</style>
