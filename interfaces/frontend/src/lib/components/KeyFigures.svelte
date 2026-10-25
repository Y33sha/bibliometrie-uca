<script lang="ts">
	// Rangée de chiffres clés en tête d'un dashboard : gros chiffre, libellé discret dessous.
	let {
		items
	}: {
		/** `open` colore le chiffre en vert open access. */
		items: { value: string; label: string; tone?: 'open' }[];
	} = $props();
</script>

<div class="key-figures">
	{#each items as item (item.label)}
		<div>
			<div class="key-figure-value" class:open={item.tone === 'open'}>{item.value}</div>
			<div class="key-figure-label">{item.label}</div>
		</div>
	{/each}
</div>

<style>
	.key-figures {
		display: flex;
		flex-wrap: wrap;
		gap: 24px 56px;
		margin-bottom: 36px;
	}
	.key-figure-value {
		font-size: 2.2rem;
		font-weight: 700;
		line-height: 1.1;
		letter-spacing: -0.02em;
	}
	.key-figure-value.open {
		color: var(--open-text);
	}
	.key-figure-label {
		margin-top: 4px;
		font-size: 0.85rem;
		color: var(--text-secondary);
	}
</style>
