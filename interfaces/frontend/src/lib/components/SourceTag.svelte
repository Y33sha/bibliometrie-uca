<script lang="ts">
	import { sourceIcon, sourceLabel } from '$lib/sources';

	let {
		source,
		href = undefined,
		id = undefined,
	}: { source: string; href?: string; id?: string | number } = $props();

	const label = $derived(sourceLabel(source));
	const icon = $derived(sourceIcon(source));
	const title = $derived(id != null ? `${label} : ${id}` : label);
</script>

{#if href}
	<a {href} target="_blank" rel="noopener" class="source-tag source-{source}" {title}>
		{#if icon}<img src={icon} alt={label} />{:else}{label}{/if}
	</a>
{:else}
	<span class="source-tag source-{source}" {title}>
		{#if icon}<img src={icon} alt={label} />{:else}{label}{/if}
	</span>
{/if}
