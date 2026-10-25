<script lang="ts">
	import DoughnutChart from '#lib/components/charts/DoughnutChart.svelte';
	import { oaStatusColor } from '#lib/components/charts/oaColors.js';

	// Répartition open access agrégée d'un dashboard, et part en open access sous l'anneau.
	let {
		oa
	}: {
		oa: { open_access: number; embargoed: number; closed: number; unknown: number; total: number };
	} = $props();

	const segments = $derived([
		{ label: 'Open Access', value: oa.open_access, color: oaStatusColor('open') },
		{ label: 'Sous embargo', value: oa.embargoed, color: oaStatusColor('embargoed') },
		{ label: 'Closed', value: oa.closed, color: oaStatusColor('closed') },
		{ label: 'Indéterminé', value: oa.unknown, color: oaStatusColor('unknown') }
	]);
</script>

<DoughnutChart {segments} />
{#if oa.total > 0}
	<div class="dash-summary">
		{Math.round((oa.open_access / oa.total) * 100)} % Open Access
		({oa.open_access.toLocaleString('fr-FR')} / {oa.total.toLocaleString('fr-FR')})
	</div>
{/if}
