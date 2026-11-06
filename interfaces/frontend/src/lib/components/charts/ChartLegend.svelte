<script lang="ts">
	import Tooltip from '#lib/components/Tooltip.svelte';

	// Légende d'un graphique : une pastille de couleur et un libellé par série, l'explication de la série au survol.
	let {
		items,
		centered = false,
	}: {
		items: { label: string; color: string; description?: string }[];
		centered?: boolean;
	} = $props();
</script>

<div class="legend" class:centered>
	{#each items as item (item.label)}
		<Tooltip text={item.description ?? ''}>
			<span class="legend-item" class:described={!!item.description}><span class="legend-dot" style="background:{item.color}"></span>{item.label}</span>
		</Tooltip>
	{/each}
</div>

<style>
	.legend {
		flex: 1 1 auto;
		display: flex;
		flex-wrap: wrap;
		gap: 6px 18px;
		font-size: var(--fs-sm);
		color: var(--text-secondary);
	}
	.centered {
		justify-content: center;
		margin-top: 8px;
	}
	.described {
		cursor: help;
		text-decoration: underline dotted var(--text-faint);
		text-underline-offset: 3px;
	}
	.legend-dot {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 3px;
		margin-right: 6px;
		vertical-align: -1px;
	}
</style>
