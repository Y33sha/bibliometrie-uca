<script module lang="ts">
	import type { LucideIcon } from '@lucide/svelte';

	/** `open` colore le chiffre en vert open access. `tooltip` s'affiche au survol. `icon` est une icône Lucide. Avec `href`, le chiffre est un lien, et son icône prend au survol la couleur `hoverColor`. */
	export type KeyFigure = {
		value: string;
		label: string;
		tone?: 'open';
		tooltip?: string;
		icon?: LucideIcon;
		href?: string;
		hoverColor?: string;
	};
</script>

<script lang="ts">
	import { tooltip } from '#lib/actions/tooltip.svelte.js';
	// Rangée de chiffres clés en tête d'un dashboard : icône facultative à gauche, gros chiffre, libellé discret dessous.
	let {
		items,
		period,
	}: {
		items: KeyFigure[];
		/** Période couverte par les chiffres, affichée en tête de la rangée. */
		period?: string;
	} = $props();
</script>

{#snippet content(item: KeyFigure)}
	{#if item.icon}<span class="key-figure-icon"><item.icon size="1em" /></span>{/if}
	<div>
		<div class="key-figure-value">{item.value}</div>
		<div class="key-figure-label">{item.label}</div>
	</div>
{/snippet}

<div class="key-figures">
	{#if period}<div class="key-figures-period">{period}</div>{/if}
	{#each items as item (item.label)}
		{#if item.href}
			<a class="key-figure key-figure-link" class:open={item.tone === 'open'} href={item.href} style:--hover-color={item.hoverColor} use:tooltip={item.tooltip}>
				{@render content(item)}
			</a>
		{:else}
			<div class="key-figure" class:open={item.tone === 'open'} use:tooltip={item.tooltip}>
				{@render content(item)}
			</div>
		{/if}
	{/each}
</div>

<style>
	.key-figures {
		/* Hauteur de la ligne des chiffres : la période et les icônes s'y centrent. */
		--value-line: calc(var(--fs-3xl) * 1.1);
		display: flex;
		flex-wrap: wrap;
		gap: 20px 40px;
		margin-bottom: 36px;
	}
	.key-figures-period {
		display: flex;
		align-items: center;
		height: var(--value-line);
		font-size: var(--fs-2xl);
		font-weight: 700;
		color: var(--accent);
		white-space: nowrap;
	}
	.key-figure {
		display: flex;
		align-items: flex-start;
		gap: 14px;
	}
	.key-figure-icon {
		display: flex;
		align-items: center;
		height: var(--value-line);
		font-size: var(--fs-2xl);
		color: var(--muted);
	}
	.key-figure-value {
		font-size: var(--fs-3xl);
		font-weight: 700;
		line-height: var(--value-line);
		letter-spacing: var(--tracking-tight);
	}
	.open .key-figure-icon,
	.open .key-figure-value {
		color: var(--open-text);
	}
	/* Chiffre cliquable : sans soulignement, l'icône prend sa couleur au survol et au focus. */
	.key-figure-link {
		color: inherit;
		text-decoration: none;
	}
	.key-figure-link .key-figure-icon {
		transition: color 0.15s;
	}
	.key-figure-link:is(:hover, :focus-visible) .key-figure-icon {
		color: var(--hover-color, var(--accent));
	}
	.key-figure-label {
		max-width: 120px;
		margin-top: 4px;
		font-size: var(--fs-sm);
		color: var(--text-secondary);
	}
</style>
