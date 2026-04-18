<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
	let checked = $state(false);

	onMount(async () => {
		try {
			const res = await fetch(base + '/api/auth/check');
			const data = await res.json();
			if (!data.authenticated) {
				goto(base + '/login', { replaceState: true });
				return;
			}
		} catch {
			goto(base + '/login', { replaceState: true });
			return;
		}
		checked = true;
	});
</script>

{#if checked}
	{@render children()}
{:else}
	<div style="text-align:center; padding:40px; color:var(--muted)">Vérification...</div>
{/if}
