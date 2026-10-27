<script lang="ts">
	import type { Snippet } from 'svelte';
	import ResultCount from '#lib/components/ResultCount.svelte';
	import { stickyHeight } from '#lib/actions/stickyHeight.js';

	// Barre d'outils d'une liste. Première ligne : recherche, nombre de résultats, export CSV et actions. Deuxième ligne : filtres. Le contenu enfant et les filtres actifs suivent.
	// La barre se masque quand la page descend au-delà d'elle, et réapparaît sous le menu supérieur dès que la page remonte. L'en-tête du tableau qui suit se colle sous la barre, ou sous le menu quand la barre est masquée.
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

	// Repère placé à l'emplacement de la barre dans la page : au-dessus du menu supérieur, la barre a quitté sa place et se colle sous le menu.
	let anchor = $state<HTMLElement | undefined>();
	let hidden = $state(false);
	let lastY = 0;

	function onscroll() {
		const y = window.scrollY;
		const headerHeight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-height')) || 0;
		const stuck = (anchor?.getBoundingClientRect().top ?? 0) < headerHeight;
		if (!stuck || y < lastY) hidden = false;
		else if (y > lastY) hidden = true;
		lastY = y;
	}
</script>

<svelte:window {onscroll} />

<div class="list-toolbar-anchor" bind:this={anchor}></div>
<div class="list-toolbar" class:hidden use:stickyHeight={!hidden}>
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
		transition: transform 0.2s ease, visibility 0s;
	}
	/* Masquée : glissée au-dessus du menu supérieur, puis retirée du parcours au clavier à la fin du glissement. */
	.list-toolbar.hidden {
		transform: translateY(calc(-100% - var(--header-height)));
		visibility: hidden;
		transition: transform 0.2s ease, visibility 0s linear 0.2s;
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
