<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Action } from 'svelte/action';

	// Mise en page d'une liste avec son panneau de filtres. Sur grand écran, le panneau ouvert longe le bord gauche de la fenêtre, du menu supérieur jusqu'en bas, et défile seul ; le contenu de la page se décale d'autant (`+layout.svelte`). Sur écran étroit, il recouvre la page.
	let {
		open = $bindable(),
		panel,
		children,
	}: {
		open: boolean;
		panel: Snippet;
		children: Snippet;
	} = $props();

	// Molette sur un panneau qui défile : arrivé en butée, le panneau garde la molette. `overscroll-behavior` ne suffit pas : Firefox, après une pause, confie la molette à la page.
	const holdWheel: Action<HTMLElement> = (node) => {
		const onWheel = (e: WheelEvent) => {
			if (node.scrollHeight <= node.clientHeight) return;
			const atTop = node.scrollTop <= 0;
			const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
			if ((e.deltaY < 0 && atTop) || (e.deltaY > 0 && atBottom)) e.preventDefault();
		};
		node.addEventListener('wheel', onWheel, { passive: false });
		return {
			destroy() {
				node.removeEventListener('wheel', onWheel);
			},
		};
	};
</script>

<div class="filter-layout" class:open>
	{#if open}
		<div class="filter-layout-panel" use:holdWheel>{@render panel()}</div>
		<button type="button" class="filter-layout-backdrop" aria-label="Fermer les filtres" onclick={() => (open = false)}></button>
	{/if}
	{@render children()}
</div>

<style>
	/* Panneau fixé contre le bord gauche, sous le menu supérieur, sur un fond teinté d'accent. Il défile seul : arrivé en butée, il ne transmet pas la molette à la page. */
	.filter-layout-panel {
		position: fixed;
		z-index: 50;
		top: var(--header-height);
		left: 0;
		bottom: 0;
		width: var(--filter-panel-width);
		padding: 0 14px 16px 20px;
		background: color-mix(in srgb, var(--accent) 4%, var(--bg));
		border-right: 1px solid var(--border-subtle);
		overflow-y: auto;
		overflow-x: hidden;
		overscroll-behavior: contain;
		scrollbar-width: thin;
		/* Barre de défilement invisible au repos, qui apparaît en fondu au survol du panneau. Chromium remplace un curseur entièrement transparent par la barre par défaut : au repos, le curseur garde 1 % d'opacité. */
		--scroll-thumb: color-mix(in srgb, var(--text-faint) 1%, transparent);
		scrollbar-color: var(--scroll-thumb) transparent;
		transition: --scroll-thumb 0.3s;
	}
	/* Au clavier, la barre apparaît tant que le focus est dans le panneau. Un clic laisse le focus sur le bouton cliqué : seul le focus clavier compte. */
	.filter-layout-panel:hover,
	.filter-layout-panel:has(:global(:focus-visible)) {
		--scroll-thumb: var(--text-faint);
	}
	.filter-layout-backdrop {
		display: none;
	}
	/* Écran étroit : le panneau recouvre la page depuis la gauche, un voile ferme le panneau au clic. */
	@media not all and (min-width: 1100px) {
		.filter-layout-panel {
			z-index: 300;
			top: 0;
			width: min(320px, 88vw);
			padding: 12px 16px;
			background: var(--card);
			border-right: none;
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
