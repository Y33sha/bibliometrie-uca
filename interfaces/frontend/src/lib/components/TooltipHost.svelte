<script lang="ts">
	// Infobulle de l'élément survolé ou focalisé, posée par l'action `tooltip` : au-dessus de l'élément, en dessous près du haut de la fenêtre, recadrée dans la largeur de la fenêtre.
	import { tooltipState } from '#lib/actions/tooltip.svelte.js';

	/** Marge minimale avec le bord de la fenêtre. */
	const MARGIN = 8;
	/** Sous cette distance au haut de la fenêtre, l'infobulle passe sous l'élément. */
	const MIN_SPACE_ABOVE = 80;

	let boxWidth = $state(0);

	const anchor = $derived(tooltipState.anchor);
	const below = $derived(anchor ? anchor.rect.top < MIN_SPACE_ABOVE : false);
	const centerX = $derived(anchor ? anchor.rect.left + anchor.rect.width / 2 : 0);
	const top = $derived(anchor ? (below ? anchor.rect.bottom : anchor.rect.top) : 0);
	const left = $derived(Math.max(MARGIN, Math.min(centerX - boxWidth / 2, window.innerWidth - MARGIN - boxWidth)));
	const arrowLeft = $derived(Math.max(MARGIN, Math.min(centerX - left, boxWidth - MARGIN)));
</script>

{#if anchor}
	<div class="tooltip-box" class:tooltip-below={below} role="tooltip" bind:offsetWidth={boxWidth} style:left="{left}px" style:top="{top}px" style:--arrow-left="{arrowLeft}px">
		{anchor.text}
	</div>
{/if}

<style>
	.tooltip-box {
		position: fixed;
		transform: translateY(calc(-100% - 8px));
		background: var(--tooltip-bg);
		color: var(--text-inverse);
		font-size: var(--fs-sm);
		line-height: 1.4;
		font-weight: 400;
		text-transform: none;
		letter-spacing: normal;
		text-align: left;
		padding: 6px 10px;
		border-radius: var(--radius);
		max-width: 500px;
		white-space: pre-line;
		word-wrap: break-word;
		z-index: 9999;
		pointer-events: none;
		box-shadow: var(--shadow-sm);
	}
	.tooltip-box::after {
		content: '';
		position: absolute;
		top: 100%;
		left: var(--arrow-left);
		transform: translateX(-50%);
		border: 5px solid transparent;
		border-top-color: var(--tooltip-bg);
	}
	.tooltip-below {
		transform: translateY(8px);
	}
	.tooltip-below::after {
		top: auto;
		bottom: 100%;
		border-top-color: transparent;
		border-bottom-color: var(--tooltip-bg);
	}
</style>
