<script lang="ts">
	import type { Snippet } from 'svelte';

	// Mise en page d'une liste avec son panneau de filtres. Sur grand écran, le panneau ouvert occupe une colonne à gauche et la liste se resserre ; le panneau suit le défilement sous la barre d'outils. Sur écran étroit, il recouvre la page.
	let {
		open = $bindable(),
		fill = false,
		panel,
		children,
	}: {
		open: boolean;
		/** Dans une colonne flexible : la mise en page occupe la hauteur restante, et son contenu est lui-même une colonne flexible. */
		fill?: boolean;
		panel: Snippet;
		children: Snippet;
	} = $props();
</script>

<div class="filter-layout" class:open class:fill>
	{#if open}
		<div class="filter-layout-panel">{@render panel()}</div>
		<button type="button" class="filter-layout-backdrop" aria-label="Fermer les filtres" onclick={() => (open = false)}></button>
	{/if}
	<div class="filter-layout-main">{@render children()}</div>
</div>

<style>
	.filter-layout.open {
		display: grid;
		grid-template-columns: 250px minmax(0, 1fr);
		column-gap: 28px;
		align-items: start;
	}
	.filter-layout-panel {
		position: sticky;
		top: calc(var(--header-height) + var(--list-toolbar-height, 0px) + 8px);
		max-height: calc(100vh - var(--header-height) - var(--list-toolbar-height, 0px) - 16px);
		overflow-y: auto;
		/* La barre de défilement ne recouvre pas les décomptes. */
		padding-right: 6px;
		scrollbar-width: thin;
	}
	.filter-layout-backdrop {
		display: none;
	}
	.filter-layout-main {
		min-width: 0;
	}
	.filter-layout.fill {
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}
	.filter-layout.fill.open {
		display: grid;
		grid-template-rows: minmax(0, 1fr);
		align-items: stretch;
	}
	.fill .filter-layout-main {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	/* Écran étroit : le panneau recouvre la page depuis la gauche, un voile ferme le panneau au clic. */
	@media not all and (min-width: 1100px) {
		.filter-layout.open {
			display: block;
		}
		.filter-layout.fill.open {
			display: flex;
		}
		.filter-layout-panel {
			position: fixed;
			z-index: 300;
			top: 0;
			left: 0;
			bottom: 0;
			width: min(320px, 88vw);
			max-height: none;
			padding: 12px 16px;
			background: var(--card);
			box-shadow: var(--shadow-md);
		}
		.filter-layout-backdrop {
			display: block;
			position: fixed;
			z-index: 299;
			inset: 0;
			border: none;
			background: var(--overlay);
			cursor: default;
		}
	}
</style>
