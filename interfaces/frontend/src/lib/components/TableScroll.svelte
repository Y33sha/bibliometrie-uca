<script lang="ts">
	import type { Snippet } from 'svelte';
	import { horizontalOverflow } from '#lib/actions/horizontalOverflow.js';

	// Conteneur d'un tableau large : défilement horizontal dès que le tableau dépasse, bords estompés du côté où le tableau continue.
	let { children }: { children: Snippet } = $props();
</script>

<div class="table-scroll" use:horizontalOverflow>
	{@render children()}
</div>
