<script lang="ts">
	import { COLLAB_VIEW, type PivotChart } from '#lib/composables/usePivotChart.svelte.js';

	// Réglages du graphique des statistiques : indicateur, comparaison, part, tri. Ils se placent dans la barre d'outils de la page, séparés par des filets.
	let { chart }: { chart: PivotChart } = $props();

	const s = $derived(chart.settings);
</script>

{#if chart.schema}
	<label class="toolbar-label">
		Indicateur&nbsp;:
		<select value={s.indicator} onchange={(e) => chart.set('indicator', e.currentTarget.value)}>
			{#each chart.schema.indicators as i (i.key)}
				<option value={i.key}>{i.unit ? `${i.label} (${i.unit})` : i.label}</option>
			{/each}
			<option value={COLLAB_VIEW}>Collaborations internationales</option>
		</select>
	</label>
	{#if !chart.isCollab}
		<span class="toolbar-sep" aria-hidden="true"></span>
		<label class="toolbar-label">
			Comparer par&nbsp;:
			<select value={s.groupBy} onchange={(e) => chart.set('groupBy', e.currentTarget.value)}>
				<option value="">Aucun</option>
				{#each chart.comparableDims as d (d.key)}
					<option value={d.key}>{d.label}</option>
				{/each}
			</select>
		</label>
		<span class="toolbar-sep" aria-hidden="true"></span>
		<label class="toolbar-label">
			<input type="checkbox" checked={s.chartMode === 'part'} onchange={(e) => chart.set('chartMode', e.currentTarget.checked ? 'part' : 'absolu')} />
			Part&nbsp;(%)
		</label>
	{/if}
{/if}
{#if !chart.isCollab && chart.sortableSeries.length}
	<span class="toolbar-sep" aria-hidden="true"></span>
	<label class="toolbar-label">
		Trier&nbsp;:
		<select value={s.chartSort} onchange={(e) => chart.set('chartSort', e.currentTarget.value)}>
			<option value="">Total</option>
			{#each chart.sortableSeries as series (series.value)}
				<option value={series.value}>% {series.label}</option>
			{/each}
		</select>
	</label>
	{#if s.chartSort}
		<button type="button" class="facet-btn" title="Sens du tri" onclick={() => chart.set('chartSortDir', s.chartSortDir === 'desc' ? 'asc' : 'desc')}>
			{s.chartSortDir === 'desc' ? '↓' : '↑'}
		</button>
	{/if}
{/if}
