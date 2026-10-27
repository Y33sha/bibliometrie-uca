<script lang="ts">
	import type { Snippet } from 'svelte';
	import ResultCount from '#lib/components/ResultCount.svelte';

	// Barre d'outils d'une liste, collante sous le menu supérieur. Première ligne : recherche, nombre de résultats, export CSV et actions. Deuxième ligne : filtres. Le contenu enfant suit, par exemple les filtres actifs.
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
		children?: Snippet;
	} = $props();

	function onkeydown(e: KeyboardEvent) {
		if (e.key !== 'Escape') return;
		search = '';
		onsearch?.();
	}
</script>

<div class="toolbar-card toolbar-sticky list-toolbar">
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

<style>
	.list-toolbar {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 12px;
	}
	.list-toolbar .toolbar {
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
