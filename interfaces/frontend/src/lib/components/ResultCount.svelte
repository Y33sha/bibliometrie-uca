<script lang="ts">
	// Nombre d'éléments d'une liste chargée par `usePaginatedFetch`, accordé en nombre. Le compteur est masqué tant que le total est inconnu : avant le premier chargement et après un échec.
	let {
		list,
		one,
		many,
	}: {
		list: { loaded: boolean; error: string | null; total: number };
		/** Libellé au singulier (0 ou 1 élément). */
		one: string;
		/** Libellé au pluriel. */
		many: string;
	} = $props();
</script>

{#if list.loaded && !list.error}
	<span class="count">{list.total.toLocaleString('fr-FR')} {list.total > 1 ? many : one}</span>
{/if}
