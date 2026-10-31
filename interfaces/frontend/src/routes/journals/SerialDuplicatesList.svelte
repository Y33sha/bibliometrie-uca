<script lang="ts">
	import { api } from '#lib/api/index.js';
	import type { components } from '#lib/api/schema.js';
	import SerialGroupsList from './SerialGroupsList.svelte';

	type DuplicatesResponse = components['schemas']['SerialDuplicatesResponse'];

	let {
		url,
		intro,
		onchange,
	}: {
		/** Route de la file : `/api/serials/same-titles`. */
		url: string;
		intro?: string;
		onchange: () => void;
	} = $props();
</script>

{#snippet introText()}{intro}{/snippet}

<SerialGroupsList
	fetchGroups={async () => (await api<DuplicatesResponse>(url)).groups}
	serialsOf={(g) => g.serials}
	keyOf={(g) => g.value}
	emptyText="Aucun groupe."
	intro={intro ? introText : undefined}
	{onchange}
/>
