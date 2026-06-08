<script lang="ts">
	import { base } from '$app/paths';
	import { sourceLabels } from '$lib/labels';

	let {
		source,
		href = undefined,
		id = undefined,
	}: { source: string; href?: string; id?: string | number } = $props();

	// Logos locaux uniquement (l'appli doit tourner hors ligne).
	const ICONS: Record<string, string> = {
		hal: `${base}/icons/hal.ico`,
		openalex: `${base}/icons/openalex.png`,
		wos: `${base}/icons/wos.ico`,
		scanr: `${base}/scanr-icon.svg`,
		theses: `${base}/icons/theses.ico`,
		crossref: `${base}/icons/crossref.ico`,
	};

	const label = $derived(sourceLabels[source] ?? source);
	const icon = $derived(ICONS[source]);
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
