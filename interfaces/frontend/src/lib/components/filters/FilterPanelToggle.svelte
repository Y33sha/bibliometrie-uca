<script lang="ts">
	import ListFilter from '@lucide/svelte/icons/list-filter';

	// Bouton qui ouvre et ferme le panneau des filtres, avec le nombre de filtres actifs.
	let { open = $bindable(), active }: { open: boolean; active: number } = $props();
</script>

<button type="button" class="facet-btn filter-toggle" class:has-selection={open} aria-expanded={open} aria-controls="filter-panel" onclick={() => (open = !open)}>
	<ListFilter size={15} />
	Filtres
	{#if active}<span class="facet-badge">{active}</span>{/if}
</button>

<style>
	.filter-toggle {
		gap: 6px;
	}
</style>
