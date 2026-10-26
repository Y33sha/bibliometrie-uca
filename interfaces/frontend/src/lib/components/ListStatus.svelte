<script lang="ts">
	import type { Snippet } from 'svelte';
	import { emptyListStatus } from '#lib/listStatus.js';

	// Liste chargée par `usePaginatedFetch`, hors tableau : erreur de chargement, chargement en cours ou message « vide » tant qu'elle n'a aucun élément, sinon son contenu, estompé pendant un rechargement.
	let {
		list,
		emptyText,
		children,
	}: {
		list: { loading: boolean; error: string | null; items: unknown[] };
		emptyText: string;
		children: Snippet;
	} = $props();

	const status = $derived(emptyListStatus(list.loading, list.error, emptyText));
</script>

{#if list.items.length === 0}
	<div class={status.cls}>{status.text}</div>
{:else}
	<div class:reloading={list.loading}>{@render children()}</div>
{/if}

<style>
	.reloading {
		opacity: 0.6;
	}
</style>
