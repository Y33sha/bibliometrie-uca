<script lang="ts">
	import { institution, pageTitle } from '#lib/institution.svelte.js';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Monographies")}</title>
</svelte:head>

<p class="hint">Livres et volumes d'actes contenant des publications du périmètre {institution.name}.</p>

<MonographsListView apiKey="monographs-list" urlSync />

<style>
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }
</style>
