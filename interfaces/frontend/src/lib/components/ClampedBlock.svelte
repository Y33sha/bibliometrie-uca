<script lang="ts">
	import { tick, type Snippet } from 'svelte';

	// Bloc replié à une hauteur maximale, en fondu sur le bas. Le bouton de dépliage paraît seulement si le contenu dépasse. Pour replier de nouveau à un changement de contenu, le parent enveloppe le bloc d'un `{#key}`.
	let {
		maxHeight,
		moreLabel,
		lessLabel = 'Réduire',
		children,
	}: {
		/** Hauteur repliée, en unité CSS. */
		maxHeight: string;
		moreLabel: string;
		lessLabel?: string;
		children: Snippet;
	} = $props();

	let block = $state<HTMLDivElement | undefined>();
	let content = $state<HTMLDivElement | undefined>();
	let open = $state(false);
	let overflows = $state(false);
	$effect(() => {
		if (!content || open) return;
		overflows = content.scrollHeight > content.clientHeight + 2;
	});

	// Au repli, la page remonte jusqu'au bloc quand son haut est passé sous la barre de navigation.
	async function toggle() {
		open = !open;
		if (open || !block) return;
		await tick();
		const margin = parseFloat(getComputedStyle(block).scrollMarginTop) || 0;
		if (block.getBoundingClientRect().top < margin) block.scrollIntoView({ block: 'start' });
	}
</script>

<div class="clamped-block" bind:this={block}>
	<div class:clamped={!open} class:overflows style:--clamped-height={maxHeight} bind:this={content}>
		{@render children()}
	</div>
	{#if overflows || open}
		<button type="button" class="btn-text read-more" onclick={toggle}>
			{open ? lessLabel : moreLabel}
		</button>
	{/if}
</div>

<style>
	/* Arrêt du défilement sous la barre de navigation, collée en haut de l'écran. */
	.clamped-block {
		scroll-margin-top: calc(var(--header-height, 0px) + 12px);
	}
	.clamped {
		max-height: var(--clamped-height);
		overflow: hidden;
	}
	.clamped.overflows {
		mask-image: linear-gradient(to bottom, black 70%, transparent);
	}
	.read-more {
		display: block;
		margin-top: 6px;
	}
</style>
