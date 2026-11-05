<script lang="ts">
	import { cssColor, fontSize } from '#lib/components/charts/cssVar.js';
	import { Chart } from '#lib/components/charts/chart.js';

	let {
		labels,
		values,
		datasetLabel = '',
		color,
		horizontal = false,
		height = 280,
		max,
		barLabel,
		tooltipLabel,
		prominentLabels = false
	}: {
		labels: string[];
		values: number[];
		datasetLabel?: string;
		/** Couleur des barres, unique ou une par barre ; défaut = variable CSS `--accent-mid`. */
		color?: string | string[];
		/** Barres horizontales (axe des valeurs en X). */
		horizontal?: boolean;
		height?: number;
		/** Borne haute de l'axe des valeurs ; défaut = ajustée aux valeurs. */
		max?: number;
		/** Texte au bout de la barre `index` ; défaut = la valeur. */
		barLabel?: (value: number, index: number) => string;
		/** Texte de l'infobulle de la barre `index` ; défaut = « libellé du jeu de données : valeur ». */
		tooltipLabel?: (value: number, index: number) => string;
		/** Libellés des catégories et texte au bout des barres en taille `--fs-md`, couleur `--text`. */
		prominentLabels?: boolean;
	} = $props();

	let canvas = $state<HTMLCanvasElement | undefined>();
	let chart: Chart | null = null;

	function render() {
		if (chart) {
			chart.destroy();
			chart = null;
		}
		if (!canvas || values.length === 0) return;
		const barColor = color ?? cssColor('accent-mid');
		const valueScale = {
			beginAtZero: true,
			max,
			ticks: { precision: 0 }
		};
		const labelStyle: { font?: { size: number }; color?: string } = prominentLabels ? { font: { size: fontSize('md') }, color: cssColor('text') } : {};
		const categoryScale = { grid: { display: false }, ticks: labelStyle };

		chart = new Chart(canvas, {
			type: 'bar',
			data: {
				labels,
				datasets: [{ label: datasetLabel, data: values, backgroundColor: barColor }]
			},
			options: {
				indexAxis: horizontal ? 'y' : 'x',
				responsive: true,
				maintainAspectRatio: false,
				// Place pour les valeurs affichées au bout des barres.
				layout: { padding: horizontal ? { right: 48 } : { top: 20 } },
				plugins: {
					legend: { display: false },
					datalabels: {
						anchor: 'end',
						align: 'end',
						...labelStyle,
						font: { weight: 600, ...labelStyle.font },
						...(barLabel && {
							formatter: (v: number, ctx: { dataIndex: number }) => barLabel(v, ctx.dataIndex)
						})
					},
					...(tooltipLabel && {
						tooltip: {
							callbacks: {
								label: (item: { dataIndex: number }) => tooltipLabel(values[item.dataIndex], item.dataIndex)
							}
						}
					})
				},
				scales: horizontal
					? { x: valueScale, y: categoryScale }
					: { y: valueScale, x: categoryScale }
			}
		});
	}

	$effect(() => {
		void labels;
		void values;
		void color;
		void horizontal;
		void max;
		void barLabel;
		void tooltipLabel;
		void prominentLabels;
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
			<tr><td></td><th scope="col">{datasetLabel || 'Nombre'}</th></tr>
		</thead>
		<tbody>
			{#each labels as label, i (i)}
				<tr><th scope="row">{label}</th><td>{tooltipLabel ? tooltipLabel(values[i], i) : values[i]}{#if barLabel} ({barLabel(values[i], i)}){/if}</td></tr>
			{/each}
		</tbody>
	</table>
</div>

<style>
	.chart-wrap {
		position: relative;
	}
</style>
