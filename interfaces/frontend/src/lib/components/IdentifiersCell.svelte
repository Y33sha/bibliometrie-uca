<script lang="ts">
	import IdentifierLink from './IdentifierLink.svelte';
	import type { components } from '#lib/api/schema.js';

	type Identifier = components['schemas']['PersonIdentifierOut'];

	let { identifiers = [] }: { identifiers?: Identifier[] } = $props();

	/**
	 * Identifiants d'un type, regroupés par valeur : une même valeur peut être attribuée par plusieurs sources, et la valeur est confirmée dès que l'une de ses attributions l'est. Les attributions que la curation a rejetées ne s'affichent pas.
	 */
	function grouped(type: string) {
		const byValue = new Map<string, boolean>();
		for (const i of identifiers) {
			if (i.id_type !== type || i.status === 'rejected') continue;
			byValue.set(
				i.id_value,
				byValue.get(i.id_value) || i.status === 'confirmed' || i.status === 'authenticated'
			);
		}
		return Array.from(byValue, ([value, confirmed]) => ({ value, confirmed }));
	}

	const types = ['orcid', 'idhal', 'idref'] as const;
</script>

<span class="tag-logos">
	{#each types as type (type)}
		{@const values = grouped(type)}
		{#if values.length}
			{#each values as id (id.value)}
				<IdentifierLink id_type={type} id_value={id.value} confirmed={id.confirmed} />
			{/each}
		{:else}
			<span class="tag tag-logo tag-placeholder"></span>
		{/if}
	{/each}
</span>
