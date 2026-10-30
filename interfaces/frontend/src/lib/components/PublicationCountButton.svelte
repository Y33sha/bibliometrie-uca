<script lang="ts">
	/** Badge du nombre de publications : bouton qui déplie la liste des publications. */
	let { count, expanded, onclick }: { count: number; expanded: boolean; onclick: () => void } = $props();
</script>

<button type="button" class="publication-count-tag" aria-expanded={expanded} {onclick}
	>{count.toLocaleString('fr-FR')} publication{count > 1 ? 's' : ''}</button
>

<style>
	.publication-count-tag {
		display: inline-block;
		font-family: inherit;
		font-size: var(--fs-sm);
		padding: 1px 7px;
		border: none;
		border-radius: var(--radius-pill);
		background: var(--accent-light);
		color: var(--accent);
		font-weight: 500;
		cursor: pointer;
		white-space: nowrap;
	}
	.publication-count-tag:hover,
	.publication-count-tag[aria-expanded='true'] {
		background: color-mix(in srgb, var(--accent) 20%, var(--accent-light));
	}
</style>
