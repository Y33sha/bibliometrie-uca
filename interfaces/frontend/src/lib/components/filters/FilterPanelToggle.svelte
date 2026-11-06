<script lang="ts">
	// Bouton qui ouvre et ferme le panneau des filtres, avec le nombre de filtres actifs.
	let { open = $bindable(), active }: { open: boolean; active: number } = $props();
</script>

<button type="button" class="facet-btn filter-toggle" class:has-selection={open} aria-expanded={open} aria-controls="filter-panel" onclick={() => (open = !open)}>
	<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
		<path d="M4 6h16M7 12h10M10 18h4" />
	</svg>
	Filtres
	{#if active}<span class="facet-badge">{active}</span>{/if}
</button>

<style>
	.filter-toggle {
		gap: 6px;
	}
</style>
