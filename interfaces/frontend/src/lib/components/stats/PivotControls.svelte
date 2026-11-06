<script lang="ts">
	import { COLLAB_VIEW, type ChartMode, type PivotChart } from '#lib/composables/usePivotChart.svelte.js';

	// Réglages du graphique des statistiques, en une phrase : « Afficher <indicateur> <comparaison> en <valeur absolue | pourcentage>, classés par <tri> ». Chaque mot réglable est une liste déroulante.
	let { chart }: { chart: PivotChart } = $props();

	const s = $derived(chart.settings);

	/** Indicateurs en groupe nominal, pour la phrase. Un indicateur absent garde son libellé, en minuscules. */
	const INDICATOR_PHRASES: Record<string, string> = {
		doc_type_grouped: 'les publications',
		oa_access: "l'accès ouvert",
		oa_voie: "les voies d'accès ouvert",
		license: 'les licences',
		citation_class: 'les publications les plus citées',
		apc_amount: 'le montant des APC',
		[COLLAB_VIEW]: 'les collaborations internationales',
	};

	function indicatorPhrase(key: string, label: string): string {
		return INDICATOR_PHRASES[key] ?? label.toLowerCase();
	}
</script>

{#if chart.schema}
	<p class="pivot-sentence">
		<span>Afficher</span>
		<select class="sentence-select" aria-label="Indicateur" value={s.indicator} onchange={(e) => chart.set('indicator', e.currentTarget.value)}>
			{#each chart.schema.indicators as i (i.key)}
				<option value={i.key}>{indicatorPhrase(i.key, i.label)}</option>
			{/each}
			<option value={COLLAB_VIEW}>{INDICATOR_PHRASES[COLLAB_VIEW]}</option>
		</select>
		{#if !chart.isCollab}
			<select class="sentence-select" aria-label="Comparaison" value={s.groupBy} onchange={(e) => chart.set('groupBy', e.currentTarget.value)}>
				{#each chart.comparableDims as d (d.key)}
					<option value={d.key}>par {d.label.toLowerCase()}</option>
				{/each}
				<option value="">au total</option>
			</select>
			<span>en</span>
			<select class="sentence-select" aria-label="Mode" value={s.chartMode} onchange={(e) => chart.set('chartMode', e.currentTarget.value as ChartMode)}>
				<option value="absolu">valeur absolue</option>
				<option value="part">pourcentage</option>
			</select>
			{#if chart.sortableSeries.length}
				<span class="after-control">, classés par</span>
				<select class="sentence-select" aria-label="Tri" value={s.chartSort} onchange={(e) => chart.set('chartSort', e.currentTarget.value)}>
					<option value="">le total</option>
					{#each chart.sortableSeries as series (series.value)}
						<option value={series.value}>la part {series.label}</option>
					{/each}
				</select>
				{#if s.chartSort}
					<button type="button" class="sort-dir" title={s.chartSortDir === 'desc' ? 'Ordre décroissant' : 'Ordre croissant'} aria-label="Sens du tri" onclick={() => chart.set('chartSortDir', s.chartSortDir === 'desc' ? 'asc' : 'desc')}>
						{s.chartSortDir === 'desc' ? '↓' : '↑'}
					</button>
				{/if}
			{/if}
		{/if}
	</p>
{/if}

<style>
	.pivot-sentence {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 6px 8px;
		margin: 0;
		font-size: var(--fs-lg);
		color: var(--text-secondary);
	}
	/* Mot réglable : texte en couleur d'accent souligné d'un trait, chevron à droite ; la liste prend la largeur du choix affiché. */
	.sentence-select {
		appearance: none;
		field-sizing: content;
		padding: 0 18px 1px 2px;
		border: none;
		border-bottom: 2px solid var(--accent);
		border-radius: 0;
		background: transparent url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%236b7280' stroke-width='1.5'/%3E%3C/svg%3E") no-repeat right 3px center;
		font: inherit;
		font-weight: 600;
		color: var(--accent);
		cursor: pointer;
	}
	.sentence-select:hover {
		color: color-mix(in srgb, var(--accent), black 20%);
		border-bottom-color: color-mix(in srgb, var(--accent), black 20%);
	}
	/* La virgule suit le contrôle qui la précède, sans espace. */
	.after-control {
		margin-left: -6px;
	}
	.sentence-select option {
		font-weight: 400;
		color: var(--text);
	}
	.sort-dir {
		align-self: center;
		border: none;
		border-radius: var(--radius);
		background: none;
		font: inherit;
		color: var(--accent);
		cursor: pointer;
	}
	.sort-dir:hover {
		background: var(--hover);
	}
</style>
