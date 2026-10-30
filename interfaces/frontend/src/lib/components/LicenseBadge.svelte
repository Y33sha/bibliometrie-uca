<script lang="ts">
	import '@flaticon/flaticon-uicons/css/brands/all.css';
	import { onMount } from 'svelte';
	import { LICENSE_ICONS, licenseLabels } from '#lib/licenses.js';

	// Licence : pictogrammes Creative Commons avec le libellé en infobulle, libellé seul pour les autres licences.
	let { license }: { license: string } = $props();

	let labels = $state<Record<string, string>>({});
	onMount(() => {
		licenseLabels()
			.then((l) => (labels = l))
			.catch(() => {});
	});

	const label = $derived(labels[license] ?? license);
	const icons = $derived(LICENSE_ICONS[license]);
</script>

{#if icons}
	<span class="license-icons" title={label} role="img" aria-label={label}>
		{#each icons as icon (icon)}<i class="fi-brands-{icon}" aria-hidden="true"></i>{/each}
	</span>
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
</style>
