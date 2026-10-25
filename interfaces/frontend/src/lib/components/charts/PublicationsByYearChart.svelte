<script lang="ts">
	import BarChart from '#lib/components/charts/BarChart.svelte';
	import { cssVar } from '#lib/components/charts/cssVar.js';

	// Publications par année. L'année en cours, incomplète, est en teinte claire pour ne pas se lire comme une baisse.
	let { data }: { data: { year: number; count: number }[] } = $props();

	const currentYear = new Date().getFullYear();
	const labels = $derived(data.map((d) => (d.year === currentYear ? `${d.year} (en cours)` : String(d.year))));
	const colors = $derived(
		data.map((d) => (d.year === currentYear ? cssVar('accent-soft') : cssVar('accent-mid')))
	);
</script>

<BarChart {labels} values={data.map((d) => d.count)} datasetLabel="Publications" color={colors} />
