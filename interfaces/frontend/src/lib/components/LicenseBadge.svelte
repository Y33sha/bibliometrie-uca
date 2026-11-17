<script lang="ts">
	import { tooltip } from '#lib/actions/tooltip.svelte.js';
	import { onMount } from 'svelte';
	import { CREATIVE_COMMONS_ICONS } from '#lib/creativeCommonsIcons.js';
	import { LICENSE_ICONS, licenseLabels } from '#lib/licenses.js';

	// Licence : pictogramme avec le libellé en infobulle, libellé seul pour les licences sans pictogramme.
	let { license }: { license: string } = $props();

	let labels = $state<Record<string, string>>({});
	onMount(() => {
		licenseLabels()
			.then((l) => (labels = l))
			.catch(() => {});
	});

	const label = $derived(labels[license] ?? license);
	const icon = $derived(LICENSE_ICONS[license]);
</script>

{#if icon && 'glyphs' in icon}
	<span class="license-icons" use:tooltip={label} role="img" aria-label={label}>
		{#each icon.glyphs as glyph (glyph)}<svg viewBox={CREATIVE_COMMONS_ICONS[glyph].viewBox} aria-hidden="true"><path d={CREATIVE_COMMONS_ICONS[glyph].d} /></svg>{/each}
	</span>
{:else if icon}
	<img class="license-image" src={icon.image} alt={label} use:tooltip={label} />
{:else}
	{label}
{/if}

<style>
	.license-icons {
		display: inline-flex;
		gap: 0.15em;
		vertical-align: middle;
		line-height: 1;
	}
	.license-icons svg {
		width: 1em;
		height: 1em;
		fill: currentColor;
	}
	.license-image {
		height: 1.4em;
		vertical-align: middle;
	}
</style>
