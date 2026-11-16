<script lang="ts">
	// Infobulle autour d'un contenu, pour les cas où aucun élément ne porte déjà l'action `tooltip`.
	import type { Snippet } from 'svelte';
	import { tooltip } from '#lib/actions/tooltip.svelte.js';

	let { text, children }: { text: string; children: Snippet } = $props();
</script>

<span class="tooltip-wrap" use:tooltip={text}>{@render children()}</span>

<style>
	.tooltip-wrap {
		display: inline;
	}
</style>
