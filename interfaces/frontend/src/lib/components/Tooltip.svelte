<script lang="ts">
	import type { Snippet } from 'svelte';
	import { tick } from 'svelte';

	interface Props {
		text: string;
		children: Snippet;
	}

	let { text, children }: Props = $props();
	let show = $state(false);
	let wrapEl: HTMLSpanElement;
	let boxEl: HTMLDivElement | undefined = $state();
	let anchorX = $state(0); // centre horizontal de l'élément déclencheur
	let y = $state(0);
	let below = $state(false);
	let left = $state(0); // bord gauche de l'infobulle (après recadrage)
	let arrowLeft = $state(0); // position de la flèche dans l'infobulle

	const MARGIN = 8; // marge minimale avec le bord de la fenêtre

	async function onEnter() {
		if (!text) return;
		const rect = wrapEl.getBoundingClientRect();
		anchorX = rect.left + rect.width / 2;
		// Si pas assez de place au-dessus (< 80px), afficher en dessous
		below = rect.top < 80;
		y = below ? rect.bottom : rect.top;
		show = true;
		// Recadrage horizontal une fois l'infobulle rendue (largeur connue)
		await tick();
		position();
	}

	function position() {
		if (!boxEl) return;
		const width = boxEl.offsetWidth;
		const maxLeft = window.innerWidth - MARGIN - width;
		// Idéalement centrée sur l'élément, sinon plaquée contre le bord
		left = Math.max(MARGIN, Math.min(anchorX - width / 2, maxLeft));
		// La flèche reste alignée sur l'élément déclencheur
		arrowLeft = Math.max(MARGIN, Math.min(anchorX - left, width - MARGIN));
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span class="tooltip-wrap" bind:this={wrapEl}
	onmouseenter={onEnter}
	onmouseleave={() => { show = false; }}
>
	{@render children()}
</span>

{#if show && text}
	<div class="tooltip-box" class:tooltip-below={below} bind:this={boxEl}
		style="left:{left}px; top:{y}px; --arrow-left:{arrowLeft}px;">
		{@html text.replace(/\n/g, '<br>')}
	</div>
{/if}

<style>
	.tooltip-wrap {
		display: inline;
	}
	.tooltip-box {
		position: fixed;
		transform: translateY(calc(-100% - 8px));
		background: #333;
		color: #fff;
		font-size: 0.78rem;
		line-height: 1.4;
		padding: 6px 10px;
		border-radius: 5px;
		max-width: 500px;
		white-space: normal;
		word-wrap: break-word;
		z-index: 9999;
		pointer-events: none;
		box-shadow: 0 2px 8px rgba(0,0,0,0.2);
	}
	.tooltip-box::after {
		content: '';
		position: absolute;
		top: 100%;
		left: var(--arrow-left);
		transform: translateX(-50%);
		border: 5px solid transparent;
		border-top-color: #333;
	}
	.tooltip-below {
		transform: translateY(8px);
	}
	.tooltip-below::after {
		top: auto;
		bottom: 100%;
		border-top-color: transparent;
		border-bottom-color: #333;
	}
</style>
