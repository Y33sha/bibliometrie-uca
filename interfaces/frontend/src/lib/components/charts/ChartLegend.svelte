<script lang="ts">
	import Tooltip from '#lib/components/Tooltip.svelte';

	// Légende d'un graphique : une pastille de couleur et un libellé par série, l'explication de la série au survol. Avec `onselect`, chaque série est un bouton : `selected` désigne la série choisie.
	let {
		items,
		centered = false,
		selected = null,
		onselect,
	}: {
		items: { label: string; color: string; description?: string }[];
		centered?: boolean;
		selected?: string | null;
		onselect?: (label: string) => void;
	} = $props();
</script>

<div class="legend" class:centered>
	{#each items as item (item.label)}
		<Tooltip text={item.description ?? ''}>
			{#if onselect}
				<button type="button" class="legend-item legend-button" aria-pressed={selected === item.label} onclick={() => onselect(item.label)}>
					<span class="legend-dot" style="background:{item.color}"></span>{item.label}
				</button>
			{:else}
				<span class="legend-item" class:described={!!item.description}><span class="legend-dot" style="background:{item.color}"></span>{item.label}</span>
			{/if}
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
	.legend-button {
		padding: 2px 6px;
		border: 1px solid transparent;
		border-radius: var(--radius);
		background: none;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}
	.legend-button:hover {
		background: var(--hover);
	}
	.legend-button[aria-pressed='true'] {
		border-color: var(--border);
		color: var(--text);
		font-weight: 600;
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
