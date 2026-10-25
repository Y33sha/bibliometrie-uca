<script lang="ts">
	// Sens de tri d'une colonne : chevron vers le haut pour un tri croissant, vers le bas pour un tri décroissant, rien si la colonne n'est pas triée.
	let { direction }: { direction: 'asc' | 'desc' | null } = $props();
</script>

{#if direction}<span class="sort-arrow chevron" class:up={direction === 'asc'} aria-hidden="true"></span>{/if}
