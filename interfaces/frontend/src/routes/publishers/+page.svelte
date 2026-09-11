<script lang="ts">
	import { institution, pageTitle } from '$lib/institution.svelte';
	import PublishersListView from '$lib/components/PublishersListView.svelte';
</script>

<svelte:head>
	<title>{pageTitle("Éditeurs")}</title>
</svelte:head>

<h1>Éditeurs</h1>
<p class="hint">
	Liste des éditeurs des revues observées sur les publications du périmètre
	{institution.name}. Cliquer sur un éditeur pour explorer son portfolio de revues et ses
	publications.
</p>

<PublishersListView apiKey="publishers-list" urlSync withPubs />

<style>
	h1 { margin: 0 0 8px; font-size: 1.5rem; }
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }
</style>
