<script lang="ts">
	import { institution, pageTitle } from '$lib/institution.svelte';
	import JournalsListView from '$lib/components/JournalsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Revues")}</title>
</svelte:head>

<h1>Revues</h1>
<p class="hint">
	Liste des revues observées sur les publications du périmètre {institution.name}. Cliquer
	sur une revue pour explorer ses publications, sa répartition par type/OA
	et ses données DOAJ.
</p>

<JournalsListView apiKey="journals-list" urlSync withPubs />

<style>
	h1 { margin: 0 0 8px; font-size: 1.5rem; }
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }
</style>
