<script lang="ts">
	import { sourceIcon, sourceIconIsRound, sourceLabel } from '#lib/sources.svelte.js';

	let {
		source,
		href = undefined,
		id = undefined,
	}: { source: string; href?: string; id?: string | number } = $props();

	const label = $derived(sourceLabel(source));
	const icon = $derived(sourceIcon(source));
	const title = $derived(id != null ? `${label} : ${id}` : label);
	const round = $derived(sourceIconIsRound(source));
</script>

{#if href}
	<a {href} target="_blank" rel="noopener" class="tag tag-logo" class:tag-logo-full={round} style:--tag-color="var(--logo-{source})" {title}>
		{#if icon}<img src={icon} alt={label} />{:else}{label}{/if}
	</a>
{:else}
	<span class="tag tag-logo" class:tag-logo-full={round} style:--tag-color="var(--logo-{source})" {title}>
		{#if icon}<img src={icon} alt={label} />{:else}{label}{/if}
	</span>
{/if}
