<script lang="ts">
	import type { Snippet } from 'svelte';
	import IconButton from '#lib/components/IconButton.svelte';

	// Titre principal d'une fiche, précédé de l'icône qui ouvre le volet d'édition de l'entité quand `onopen` est fourni (session admin), et suivi des liens vers les identifiants de l'entité.
	let {
		onopen,
		identifierLinks,
		children,
	}: {
		onopen?: () => void;
		/** Liens vers les identifiants de l'entité, centrés sur la première ligne du titre. */
		identifierLinks?: Snippet;
		children: Snippet;
	} = $props();
</script>

<div class="title-row">
	{#if onopen}<IconButton icon="panel" label="Ouvrir le volet" onclick={onopen} />{/if}
	{@render children()}
	{#if identifierLinks}<span class="title-identifiers">{@render identifierLinks()}</span>{/if}
</div>

<style>
	.title-row {
		position: relative;
		display: flex;
		align-items: flex-start;
		gap: 10px;
	}
	/* Icône centrée sur la première ligne du titre. */
	.title-row > :global(.icon-btn) {
		flex: none;
		margin-top: 4px;
	}
	/* Hauteur de la première ligne du titre (`.entity-title`) : les liens s'y centrent. */
	.title-identifiers {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		height: calc(var(--fs-3xl) * 1.2);
	}
	/* Écran large : l'icône se place dans la marge, à gauche du titre, qui reste aligné sur le contenu. */
	@media (min-width: 1440px) {
		.title-row > :global(.icon-btn) {
			position: absolute;
			top: 0;
			right: 100%;
			margin-right: 8px;
		}
	}
</style>
