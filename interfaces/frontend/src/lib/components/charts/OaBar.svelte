<script lang="ts">
	// Répartition open access agrégée d'un dashboard : part en open access en grand, barre empilée, légende chiffrée.
	let {
		oa
	}: {
		oa: { open_access: number; embargoed: number; closed: number; unknown: number; total: number };
	} = $props();

	const segments = $derived([
		{ label: 'Ouvert', value: oa.open_access, color: 'var(--open)' },
		{ label: 'Sous embargo', value: oa.embargoed, color: 'var(--embargoed)' },
		{ label: 'Fermé', value: oa.closed, color: 'var(--closed)' },
		{ label: 'Indéterminé', value: oa.unknown, color: 'var(--unknown)' }
	]);
	const share = $derived(oa.total > 0 ? Math.round((oa.open_access / oa.total) * 100) : 0);
</script>

{#if oa.total > 0}
	<div class="oa-headline">
		<span class="oa-share">{share} %</span>
		<span>des publications sont en open access</span>
	</div>
	<div class="oa-bar">
		{#each segments as s (s.label)}
			{#if s.value > 0}
				<span
					style="width: {(s.value / oa.total) * 100}%; background: {s.color}"
					title="{s.label} : {s.value.toLocaleString('fr-FR')}"
				></span>
			{/if}
		{/each}
	</div>
	<ul class="oa-legend">
		{#each segments as s (s.label)}
			<li>
				<span class="swatch" style="background: {s.color}"></span>{s.label}
				<span class="oa-count">{s.value.toLocaleString('fr-FR')}</span>
			</li>
		{/each}
	</ul>
{:else}
	<p class="oa-empty">Aucune publication.</p>
{/if}

<style>
	.oa-headline {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 10px;
		font-size: 0.9rem;
		color: var(--text-secondary);
	}
	.oa-share {
		font-size: 2.6rem;
		font-weight: 700;
		letter-spacing: -0.02em;
		color: var(--open-text);
	}
	.oa-bar {
		display: flex;
		height: 24px;
		margin-top: 16px;
		border-radius: var(--radius);
		overflow: hidden;
	}
	.oa-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 18px;
		margin: 14px 0 0;
		padding: 0;
		list-style: none;
		font-size: 0.85rem;
	}
	.oa-legend li {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.swatch {
		width: 10px;
		height: 10px;
		border-radius: 3px;
	}
	.oa-count {
		color: var(--muted);
	}
	.oa-empty {
		color: var(--muted);
	}
</style>
