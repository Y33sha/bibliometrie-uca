<script lang="ts">
	import { Chart } from '#lib/components/charts/chart.js';
	import { cssColor } from '#lib/components/charts/cssVar.js';
	import { formatCount } from '#lib/plural.js';
	import { formatPercent } from '#lib/utils.js';

	// Barres par année : le total de l'année en gris ; la part choisie, en couleur, superposée au bas de chaque barre. Le gris, presque opaque, reste visible sur les années atténuées (année en cours et années ultérieures).
	let {
		years,
		totals,
		totalLabel,
		part = null,
		partColor,
		height = 280,
	}: {
		years: number[];
		/** Total de chaque année, dans l'ordre de `years`. */
		totals: number[];
		/** Nom du total, au singulier : « publication avec adresse ». */
		totalLabel: string;
		/** Part du total : `values` suit `years`. */
		part?: { label: string; values: number[] } | null;
		partColor: string;
		height?: number;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	const totalCount = (i: number) => formatCount(totals[i], totalLabel);
	const share = (i: number) => (part ? `${part.label} : ${part.values[i]} sur ${totalCount(i)} (${formatPercent(totals[i] ? part.values[i] / totals[i] : 0)})` : '');

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || years.length === 0) return;
		const bar = { grouped: false, borderRadius: 4, borderSkipped: 'start' as const };
		// Chart.js annote les tableaux de données reçus : il reçoit des copies, les tableaux réactifs de Svelte refusent ces annotations.
		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels: years.map(String),
				datasets: [
					...(part ? [{ label: part.label, data: [...part.values], backgroundColor: partColor, order: 0, ...bar }] : []),
					{ label: totalLabel, data: [...totals], backgroundColor: `${cssColor('text-faint')}cc`, order: 1, ...bar },
				],
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				animation: false,
				interaction: { mode: 'index', intersect: false },
				plugins: {
					legend: { display: false },
					datalabels: { display: false },
					tooltip: {
						displayColors: false,
						filter: (item) => item.datasetIndex === 0,
						callbacks: { label: (item) => (part ? share(item.dataIndex) : totalCount(item.dataIndex)) },
					},
				},
				scales: {
					x: { grid: { display: false } },
					y: { beginAtZero: true, ticks: { precision: 0 } },
				},
			},
		});
	}

	$effect(() => {
		void years;
		void totals;
		void part;
		void partColor;
		void canvas;
		render();
		return () => {
			if (chart) {
				chart.destroy();
				chart = null;
			}
		};
	});
</script>

<!-- Le graphique est dessiné dans un canvas : les lecteurs d'écran lisent le tableau des données. -->
<div class="chart-wrap" style="height: {height}px">
	<canvas bind:this={canvas} aria-hidden="true"></canvas>
</div>
<div class="visually-hidden">
	<table>
		<thead>
			<tr>
				<td></td>
				<th scope="col">{totalLabel}</th>
				{#if part}<th scope="col">{part.label}</th>{/if}
			</tr>
		</thead>
		<tbody>
			{#each years as year, i (year)}
				<tr>
					<th scope="row">{year}</th>
					<td>{totals[i]}</td>
					{#if part}<td>{part.values[i]}</td>{/if}
				</tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
