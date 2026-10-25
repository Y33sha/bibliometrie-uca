<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import type { Snippet } from 'svelte';
	import { auth } from '#lib/api/index.js';

	let { children }: { children: Snippet } = $props();
	let checked = $state(false);

	onMount(async () => {
		try {
			const data = await auth.check();
			if (!data.authenticated) {
				goto(resolve('login'), { replaceState: true });
				return;
			}
		} catch {
			goto(resolve('login'), { replaceState: true });
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
