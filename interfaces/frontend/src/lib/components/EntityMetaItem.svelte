<script lang="ts">
	import type { Snippet } from 'svelte';

	// Métadonnée de l'en-tête d'une entité : libellé et valeurs passent à la ligne ensemble.
	let { label, children }: { label: string; children: Snippet } = $props();
</script>

<span class="entity-meta-item">
	<span class="entity-meta-label">{label}</span>
	{@render children()}
</span>
