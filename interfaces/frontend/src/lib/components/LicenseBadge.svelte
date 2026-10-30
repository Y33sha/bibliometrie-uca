<script lang="ts">
	import '@flaticon/flaticon-uicons/css/brands/all.css';
	import { onMount } from 'svelte';
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
	<span class="license-icons" title={label} role="img" aria-label={label}>
		{#each icon.glyphs as glyph (glyph)}<i class="fi-brands-{glyph}" aria-hidden="true"></i>{/each}
	</span>
{:else if icon}
	<img class="license-image" src={icon.image} alt={label} title={label} />
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
	.license-icons i {
		display: inline-flex;
	}
	.license-image {
		height: 1.4em;
		vertical-align: middle;
	}
</style>
