<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		text: string;
		children: Snippet;
	}

	let { text, children }: Props = $props();
	let show = $state(false);
	let wrapEl: HTMLSpanElement;
	let x = $state(0);
	let y = $state(0);

	function onEnter() {
		if (!text) return;
		const rect = wrapEl.getBoundingClientRect();
		x = rect.left + rect.width / 2;
		y = rect.top;
		show = true;
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
	<div class="tooltip-box" style="left:{x}px; top:{y}px;">
		{@html text.replace(/\n/g, '<br>')}
	</div>
{/if}

<style>
	.tooltip-wrap {
		display: inline;
	}
	.tooltip-box {
		position: fixed;
		transform: translate(-50%, calc(-100% - 8px));
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
		left: 50%;
		transform: translateX(-50%);
		border: 5px solid transparent;
		border-top-color: #333;
	}
</style>
