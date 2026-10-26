<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import type { Snippet } from 'svelte';
	import { isAdmin, loginUrl, session } from '#lib/session.svelte.js';

	let { children }: { children: Snippet } = $props();

	// Sans le rôle admin, renvoie vers la connexion, qui ramène ensuite à la page demandée.
	$effect(() => {
		if (session.loaded && !isAdmin()) goto(loginUrl(page.url), { replaceState: true });
	});
</script>

{#if isAdmin()}
	{@render children()}
{:else}
	<div style="text-align:center; padding:40px; color:var(--muted)">Vérification...</div>
{/if}
