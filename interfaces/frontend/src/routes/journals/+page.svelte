<script lang="ts">
	import { institution, pageTitle } from '#lib/institution.svelte.js';
	import SerialsListView from '#lib/components/SerialsListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Publications en série")}</title>
</svelte:head>

<h1>Publications en série</h1>
<p class="hint">
	Liste des publications en série observées sur les publications du périmètre {institution.name}. Cliquer
	sur une publication en série pour explorer ses publications, sa répartition par type/OA
	et ses données DOAJ.
</p>

<SerialsListView apiKey="journals-list" urlSync withPubs />

<style>
	h1 { margin: 0 0 8px; font-size: 1.5rem; }
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }
</style>
