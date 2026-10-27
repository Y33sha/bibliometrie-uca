<script lang="ts">
	import type { Snippet } from 'svelte';
	import IconButton from '#lib/components/IconButton.svelte';

	// Titre principal d'une fiche, précédé de l'icône qui ouvre le volet d'édition de l'entité quand `onopen` est fourni (session admin).
	let { onopen, children }: { onopen?: () => void; children: Snippet } = $props();
</script>

<div class="title-row">
	{#if onopen}<IconButton icon="panel" label="Ouvrir le volet" onclick={onopen} />{/if}
	{@render children()}
</div>

<style>
	.title-row {
		display: flex;
		align-items: flex-start;
		gap: 10px;
	}
	/* Icône centrée sur la première ligne du titre. */
	.title-row > :global(.icon-btn) {
		flex: none;
		margin-top: 4px;
	}
</style>
