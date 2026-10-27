<script lang="ts">
	import type { Snippet } from 'svelte';
	import { pageTitle } from '#lib/institution.svelte.js';

	// En-tête d'une page hors fiche d'entité. Le nom de la page sert de titre de niveau 1 et de titre du navigateur.
	let {
		title,
		hidden = false,
		children,
	}: {
		title: string;
		/** Titre lu par les lecteurs d'écran seulement : pages de liste, dont la barre d'outils ouvre la page. */
		hidden?: boolean;
		/** Description affichée sous le titre. */
		children?: Snippet;
	} = $props();
</script>

<svelte:head>
	<title>{pageTitle(title)}</title>
</svelte:head>

{#if hidden}
	<h1 class="visually-hidden">{title}</h1>
{:else}
	<header class="page-header">
		<h1>{title}</h1>
		{#if children}<p class="page-description">{@render children()}</p>{/if}
	</header>
{/if}

<style>
	.page-header {
		margin-bottom: 16px;
	}
	h1 {
		margin: 0;
		font-size: 1.5rem;
		line-height: 1.2;
		font-weight: 700;
		letter-spacing: -0.01em;
	}
	.page-description {
		margin: 6px 0 0;
		max-width: 80ch;
		color: var(--text-secondary);
		font-size: 0.9rem;
		line-height: 1.5;
	}
</style>
