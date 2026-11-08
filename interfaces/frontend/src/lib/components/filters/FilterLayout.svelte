<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Action } from 'svelte/action';

	// Mise en page d'une liste avec son panneau de filtres. Sur grand écran, le panneau ouvert occupe une colonne à gauche et la liste se resserre ; le panneau suit le défilement sous la barre d'outils, et défile seul. Sur écran étroit, il recouvre la page.
	let {
		open = $bindable(),
		panel,
		children,
	}: {
		open: boolean;
		panel: Snippet;
		children: Snippet;
	} = $props();

	/** Marge entre le bas du panneau et le bas de la fenêtre. */
	const BOTTOM_GAP = 8;
	/** Durée du glissement de la barre d'outils (`ListToolbar`), après lequel le panneau a trouvé sa place. */
	const TOOLBAR_SLIDE_MS = 250;

	// Le bas du panneau reste dans la fenêtre : sa hauteur maximale part de sa position réelle, qui change au défilement (le panneau rejoint sa place collante) et au glissement de la barre d'outils. Le panneau recouvrant la page (écran étroit) garde la hauteur de la fenêtre.
	const fitToViewport: Action<HTMLElement> = (node) => {
		let frame = 0;
		let settle: ReturnType<typeof setTimeout>;
		const update = () => {
			if (getComputedStyle(node).position !== 'sticky') {
				node.style.maxHeight = '';
				return;
			}
			node.style.maxHeight = `${Math.max(160, innerHeight - node.getBoundingClientRect().top - BOTTOM_GAP)}px`;
		};
		const schedule = () => {
			cancelAnimationFrame(frame);
			frame = requestAnimationFrame(update);
			clearTimeout(settle);
			settle = setTimeout(update, TOOLBAR_SLIDE_MS);
		};
		// Molette sur un panneau qui défile : arrivé en butée, le panneau garde la molette. `overscroll-behavior` ne suffit pas : Firefox, après une pause, confie la molette à la page.
		const onWheel = (e: WheelEvent) => {
			if (node.scrollHeight <= node.clientHeight) return;
			const atTop = node.scrollTop <= 0;
			const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 1;
			if ((e.deltaY < 0 && atTop) || (e.deltaY > 0 && atBottom)) e.preventDefault();
		};
		node.addEventListener('wheel', onWheel, { passive: false });
		update();
		addEventListener('scroll', schedule, { passive: true });
		addEventListener('resize', schedule);
		// Un changement de mise en page déplace aussi le panneau, sans défilement : barre des filtres actifs qui apparaît, liste qui se charge.
		const layout = new ResizeObserver(schedule);
		layout.observe(document.body);
		return {
			destroy() {
				cancelAnimationFrame(frame);
				clearTimeout(settle);
				layout.disconnect();
				node.removeEventListener('wheel', onWheel);
				removeEventListener('scroll', schedule);
				removeEventListener('resize', schedule);
			},
		};
	};
</script>

<div class="filter-layout" class:open>
	{#if open}
		<div class="filter-layout-panel" use:fitToViewport>{@render panel()}</div>
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
	/* Le panneau défile seul : arrivé en butée, il ne transmet pas la molette à la page. */
	.filter-layout-panel {
		position: sticky;
		top: calc(var(--header-height) + var(--list-toolbar-height, 0px) + 8px);
		overflow-y: auto;
		overflow-x: hidden;
		overscroll-behavior: contain;
		/* La barre de défilement ne recouvre pas les décomptes. */
		padding-right: 6px;
		scrollbar-width: thin;
		/* Barre de défilement invisible au repos, qui apparaît en fondu au survol du panneau. Chromium remplace un curseur entièrement transparent par la barre par défaut : au repos, le curseur garde 1 % d'opacité. */
		--scroll-thumb: color-mix(in srgb, var(--text-faint) 1%, transparent);
		scrollbar-color: var(--scroll-thumb) transparent;
		transition: --scroll-thumb 0.3s;
	}
	/* Barre d'outils détachée (`ListToolbar`) : le panneau glisse au même rythme qu'elle. */
	:global(:root[data-list-toolbar='detached']) .filter-layout-panel {
		transition: --scroll-thumb 0.3s, top var(--list-toolbar-slide) ease;
	}
	/* Au clavier, la barre apparaît tant que le focus est dans le panneau. Un clic laisse le focus sur le bouton cliqué : seul le focus clavier compte. */
	.filter-layout-panel:hover,
	.filter-layout-panel:has(:global(:focus-visible)) {
		--scroll-thumb: var(--text-faint);
	}
	.filter-layout-backdrop {
		display: none;
	}
	.filter-layout-main {
		min-width: 0;
	}
	/* Écran étroit : le panneau recouvre la page depuis la gauche, un voile ferme le panneau au clic. */
	@media not all and (min-width: 1100px) {
		.filter-layout.open {
			display: block;
		}
		.filter-layout-panel {
			position: fixed;
			z-index: 300;
			top: 0;
			left: 0;
			bottom: 0;
			width: min(320px, 88vw);
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
