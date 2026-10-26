<script lang="ts">
	import { api } from '#lib/api/index.js';
	import { sourceLabel } from '#lib/sources.svelte.js';
	import type { components } from '#lib/api/schema.js';
	import SerialGroupsList from './SerialGroupsList.svelte';

	type Response = components['schemas']['DoiNamespaceConflictsResponse'];
	type Conflict = components['schemas']['DoiNamespaceConflict'];

	let {
		onchange,
	}: {
		onchange: () => void;
	} = $props();

	/** « 32 documents OpenAlex », « 20 documents OpenAlex, 12 HAL ». */
	function sources(c: Conflict): string {
		return Object.entries(c.sources)
			.map(([source, n], i) =>
				i === 0
					? `${n} document${n > 1 ? 's' : ''} ${sourceLabel(source)}`
					: `${n} ${sourceLabel(source)}`
			)
			.join(', ');
	}

	const percent = new Intl.NumberFormat('fr-FR', { style: 'percent', maximumFractionDigits: 0 });
</script>

<SerialGroupsList
	fetchGroups={async () => (await api<Response>('/api/serials/doi-namespace-conflicts')).conflicts}
	serialsOf={(c) => [c.namespace_serial, c.record_serial]}
	keyOf={(c) => `${c.record_serial.id}-${c.namespace_serial.id}`}
	emptyText="Aucune contradiction."
	{onchange}
>
	{#snippet intro()}
		Documents dont la publication en série diffère de celle que désigne l'espace de noms de leur DOI. La première ligne de chaque paire est la publication en série de l'espace de noms, la seconde l'attribution concurrente.
	{/snippet}
	{#snippet groupHead(c: Conflict)}
		<code>{c.namespace}</code> : {c.dois} DOI sur {c.documents} documents.
		{percent.format(c.share)} des DOI désignent {c.namespace_serial.title}.<br />
		Attribution concurrente : {c.record_serial.title} ({sources(c)}).
	{/snippet}
</SerialGroupsList>
