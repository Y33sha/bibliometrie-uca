<script lang="ts">
	import type { Snippet } from 'svelte';
	import ResultCount from '#lib/components/ResultCount.svelte';
	import { stickyHeight } from '#lib/actions/stickyHeight.js';

	// Barre d'outils d'une liste. Première ligne : recherche, nombre de résultats, export CSV et actions. Deuxième ligne : filtres. Le contenu enfant et les filtres actifs suivent.
	// Collée sous le menu supérieur, la barre suit le défilement pixel par pixel : elle glisse sous le menu quand la page descend, et en ressort quand la page remonte. L'en-tête du tableau qui suit se colle sous sa part visible.
	let {
		search = $bindable(),
		placeholder = 'Rechercher',
		onsearch,
		list,
		one,
		many,
		exportUrl,
		actions,
		filters,
		activeFilters,
		children,
	}: {
		/** Terme de recherche. Sans valeur, la barre n'affiche aucun champ de recherche. */
		search?: string;
		placeholder?: string;
		/** Appelé à chaque saisie et quand Échap vide le champ. */
		onsearch?: () => void;
		/** Liste dont la barre affiche le nombre d'éléments. */
		list: { loaded: boolean; error: string | null; total: number };
		/** Libellé du compteur au singulier. */
		one: string;
		/** Libellé du compteur au pluriel. */
		many: string;
		/** Adresse de l'export CSV de la liste filtrée. */
		exportUrl?: string;
		actions?: Snippet;
		filters?: Snippet;
		/** Filtres actifs, au bas de la barre. */
		activeFilters?: Snippet;
		children?: Snippet;
	} = $props();

	function onkeydown(e: KeyboardEvent) {
		if (e.key !== 'Escape') return;
		search = '';
		onsearch?.();
	}

	// Repère placé à l'emplacement de la barre dans la page : sa distance au-dessus du menu supérieur est le chemin que la barre aurait parcouru sans être collée.
	let anchor = $state<HTMLElement | undefined>();
	let bar = $state<HTMLElement | undefined>();
	// Part de la barre glissée sous le menu, en pixels, de zéro à la hauteur de la barre.
	let offset = $state(0);
	const hidden = $derived(bar !== undefined && offset >= bar.offsetHeight);
	let lastY = 0;

	// Instant du dernier geste de défilement : molette, glissé tactile, touche de défilement. Le navigateur décale aussi la page quand la hauteur de la barre change (panneau ouvert, filtre ajouté) ; seul un défilement vers le bas qui suit un geste masque la barre.
	let lastGesture = 0;
	const GESTURE_WINDOW_MS = 300;
	const SCROLL_KEYS = new Set(['ArrowDown', 'PageDown', 'End', ' ']);

	function markGesture() {
		lastGesture = performance.now();
	}

	function onScrollKey(e: KeyboardEvent) {
		const target = e.target as HTMLElement | null;
		if (target?.closest('input, textarea, select, [contenteditable]')) return;
		if (SCROLL_KEYS.has(e.key)) markGesture();
	}

	function onscroll() {
		if (!anchor || !bar) return;
		const y = window.scrollY;
		const delta = y - lastY;
		lastY = y;
		const headerHeight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-height')) || 0;
		// La barre glisse au plus de sa hauteur, et au plus du chemin parcouru depuis sa place.
		const limit = Math.min(bar.offsetHeight, Math.max(0, headerHeight - anchor.getBoundingClientRect().top));
		const gesture = performance.now() - lastGesture < GESTURE_WINDOW_MS;
		let next = offset;
		if (delta > 0 && gesture) next += delta;
		else if (delta < 0) next += delta;
		offset = Math.min(limit, Math.max(0, next));
	}
</script>

<svelte:window {onscroll} onwheel={markGesture} ontouchmove={markGesture} onkeydown={onScrollKey} />

<div class="list-toolbar-anchor" bind:this={anchor}></div>
<div class="list-toolbar" class:hidden bind:this={bar} style:transform={offset ? `translateY(${-offset}px)` : undefined} use:stickyHeight={offset}>
	<div class="toolbar-card">
		<div class="toolbar">
			{#if search !== undefined}
				<input type="search" class="list-search" {placeholder} aria-label={placeholder} bind:value={search} oninput={onsearch} {onkeydown} />
			{/if}
			<ResultCount {list} {one} {many} />
			{#if exportUrl}<a href={exportUrl} class="export-btn" download>Export CSV</a>{/if}
			{@render actions?.()}
		</div>
		{#if filters}
			<div class="toolbar">
				<span class="filters-label">Filtrer par&nbsp;:</span>
				{@render filters()}
			</div>
		{/if}
		{@render children?.()}
	</div>
	{@render activeFilters?.()}
</div>

<style>
	.list-toolbar {
		position: sticky;
		top: var(--header-height);
		z-index: 40;
		margin-bottom: 12px;
		background: var(--bg);
	}
	/* Entièrement glissée sous le menu : retirée du parcours au clavier. */
	.list-toolbar.hidden {
		visibility: hidden;
	}
	.toolbar-card {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	.toolbar-card .toolbar {
		margin-bottom: 0;
	}
	.list-search {
		flex: 1;
		min-width: 220px;
	}
	.filters-label {
		font-size: 0.9rem;
		color: var(--muted);
		white-space: nowrap;
	}
</style>
