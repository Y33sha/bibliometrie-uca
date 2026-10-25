<script lang="ts">
	import { api } from '#lib/api/index.js';
	import type { components } from '#lib/api/schema.js';
	import SerialGroupsList from './SerialGroupsList.svelte';

	type DuplicatesResponse = components['schemas']['SerialDuplicatesResponse'];
	type Group = components['schemas']['SerialDuplicateGroup'];

	let {
		url,
		valueLabel,
		intro,
		onchange,
	}: {
		/** Route de la file : `/api/serials/same-titles` ou `/api/serials/shared-issns`. */
		url: string;
		/** Libellé de la valeur partagée, affiché en tête de chaque groupe (« ISSN ») ; sans libellé, les groupes se suivent sans en-tête. */
		valueLabel?: string;
		intro?: string;
		onchange: () => void;
	} = $props();
</script>

{#snippet introText()}{intro}{/snippet}
{#snippet sharedValue(group: Group)}<strong>{valueLabel} {group.value}</strong>{/snippet}

<SerialGroupsList
	fetchGroups={async () => (await api<DuplicatesResponse>(url)).groups}
	serialsOf={(g) => g.serials}
	keyOf={(g) => g.value}
	emptyText="Aucun groupe."
	intro={intro ? introText : undefined}
	groupHead={valueLabel ? sharedValue : undefined}
	{onchange}
/>
