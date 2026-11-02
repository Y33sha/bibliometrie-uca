<script module lang="ts">
	/** `open` colore le chiffre en vert open access. `tooltip` s'affiche au survol. `icon` est le nom d'une icône Flaticon UIcons, sans le préfixe `fi-rr-`. */
	export type KeyFigure = { value: string; label: string; tone?: 'open'; tooltip?: string; icon?: string };
</script>

<script lang="ts">
	// Rangée de chiffres clés en tête d'un dashboard : icône facultative à gauche, gros chiffre, libellé discret dessous.
	let { items }: { items: KeyFigure[] } = $props();
</script>

<div class="key-figures">
	{#each items as item (item.label)}
		<div class="key-figure" class:open={item.tone === 'open'} title={item.tooltip}>
			{#if item.icon}<i class="fi fi-rr-{item.icon} key-figure-icon" aria-hidden="true"></i>{/if}
			<div>
				<div class="key-figure-value">{item.value}</div>
				<div class="key-figure-label">{item.label}</div>
			</div>
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
	.key-figure {
		display: flex;
		align-items: flex-start;
		gap: 14px;
	}
	/* Icône centrée sur la ligne du chiffre, quelle que soit la hauteur du libellé. */
	.key-figure-icon {
		display: flex;
		align-items: center;
		height: calc(var(--fs-4xl) * 1.1);
		font-size: var(--fs-3xl);
		color: var(--muted);
	}
	.key-figure-value {
		font-size: var(--fs-4xl);
		font-weight: 700;
		line-height: 1.1;
		letter-spacing: -0.02em;
	}
	.open .key-figure-icon,
	.open .key-figure-value {
		color: var(--open-text);
	}
	.key-figure-label {
		max-width: 120px;
		margin-top: 4px;
		font-size: var(--fs-sm);
		color: var(--text-secondary);
	}
</style>
