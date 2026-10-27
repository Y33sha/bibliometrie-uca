<script lang="ts">
	import type { Snippet } from 'svelte';
	import { scrollFade } from '#lib/actions/scrollFade.js';

	// Conteneur d'un tableau large : défilement horizontal sur écran étroit, bords estompés du côté où le tableau continue.
	let { children }: { children: Snippet } = $props();
</script>

<div class="table-scroll" use:scrollFade>
	{@render children()}
</div>
