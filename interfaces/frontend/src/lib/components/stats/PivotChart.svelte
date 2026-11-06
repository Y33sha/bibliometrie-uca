<script lang="ts">
	import ChartLegend from '#lib/components/charts/ChartLegend.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import CollaborationMap from '#lib/components/stats/CollaborationMap.svelte';
	import { CHART_PAGE_SIZE, type PivotChart } from '#lib/composables/usePivotChart.svelte.js';

	// Graphique des statistiques : légende, graphique, pagination de l'axe à forte cardinalité ; ou carte des collaborations internationales. Le graphique occupe la hauteur laissée par la page, dans une colonne flexible.
	let { chart }: { chart: PivotChart } = $props();

	let canvas: HTMLCanvasElement | undefined = $state();
	$effect(() => {
		chart.attach(canvas);
	});
</script>

{#if chart.isCollab}
	<!-- Carte des collaborations internationales -->
	<section class="collab-section">
		<CollaborationMap params={chart.filterKey} />
	</section>
{:else}
	<!-- Histogramme du pivot -->
	<div class="chart-header">
		{#if chart.legendItems.length > 1}
			<ChartLegend items={chart.legendItems} />
		{/if}
	</div>
	<div class="chart-area">
		<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le tableau des données. -->
		<canvas bind:this={canvas} aria-hidden="true"></canvas>
		{#if chart.table}
			<div class="visually-hidden">
				<table>
					<thead>
						<tr><td></td>{#each chart.table.columns as c, i (i)}<th scope="col">{c}</th>{/each}</tr>
					</thead>
					<tbody>
						{#each chart.table.rows as row, i (i)}
							<tr><th scope="row">{row.label}</th>{#each row.values as v, j (j)}<td>{v}</td>{/each}</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
	{#if chart.catTotal > CHART_PAGE_SIZE}
		<Pagination
			page={chart.settings.chartPage}
			pages={Math.ceil(chart.catTotal / CHART_PAGE_SIZE)}
			onchange={(p) => chart.set('chartPage', p)}
		/>
	{/if}
{/if}

<style>
	.collab-section {
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	/* Légende, au-dessus du graphique. */
	.chart-header {
		display: flex;
		align-items: center;
		gap: 16px;
		margin-bottom: 8px;
	}
	.chart-area {
		margin-bottom: 16px;
		position: relative;
		flex: 1 1 auto;
		min-height: 360px;
	}
</style>
