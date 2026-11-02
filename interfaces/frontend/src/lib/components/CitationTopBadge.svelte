<script lang="ts">
	import { citationTopLabels } from '#lib/labels.js';

	// Seuil de citation le plus haut atteint (`CitationTop` côté API).
	let { top }: { top: string } = $props();
</script>

<span class="citation-top citation-{top}">{citationTopLabels[top] ?? top}</span>

<style>
	.citation-top {
		display: inline-block;
		padding: 2px 7px;
		border-radius: var(--radius);
		font-size: var(--fs-sm);
		font-weight: 500;
		white-space: nowrap;
	}
	.citation-top_1_percent {
		background: var(--accent);
		color: var(--accent-light);
	}
	.citation-top_10_percent {
		background: var(--accent-light);
		color: var(--accent);
	}
</style>
