<script lang="ts">
	import SourceTag from '#lib/components/SourceTag.svelte';

	// Liens vers les enregistrements d'une publication dans ses sources, une case par source : une case vide garde l'alignement des colonnes d'une ligne à l'autre.
	let {
		ids,
		urls
	}: {
		/** Identifiant de la publication dans chaque source affichée, dans l'ordre d'affichage. */
		ids: [source: string, id: string | null | undefined][];
		urls: Record<string, string>;
	} = $props();
</script>

{#each ids as [source, id] (source)}
	{#if id}
		<SourceTag {source} {id} href={urls[source]} />
	{:else}
		<span class="source-tag source-placeholder"></span>
	{/if}
{/each}
