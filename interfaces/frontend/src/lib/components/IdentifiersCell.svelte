<script lang="ts">
	import IdentifierLink from './IdentifierLink.svelte';

	type Identifier = { value: string; confirmed?: boolean };

	let {
		orcids = null,
		idhals = null,
		idrefs = null,
	}: {
		orcids?: Identifier[] | null;
		idhals?: Identifier[] | null;
		idrefs?: Identifier[] | null;
	} = $props();
</script>

<span class="id-cell">
	{#if orcids && orcids.length}
		{#each orcids as id (id.value)}
			<IdentifierLink id_type="orcid" id_value={id.value} confirmed={id.confirmed ?? false} />
		{/each}
	{:else}
		<span class="id-icon id-placeholder"></span>
	{/if}

	{#if idhals && idhals.length}
		{#each idhals as id (id.value)}
			<IdentifierLink id_type="idhal" id_value={id.value} confirmed={id.confirmed ?? false} />
		{/each}
	{:else}
		<span class="id-icon id-placeholder"></span>
	{/if}

	{#if idrefs && idrefs.length}
		{#each idrefs as id (id.value)}
			<IdentifierLink id_type="idref" id_value={id.value} confirmed={id.confirmed ?? false} />
		{/each}
	{:else}
		<span class="id-icon id-placeholder"></span>
	{/if}
</span>

<style>
	.id-cell {
		display: inline-flex;
		gap: 4px;
		align-items: center;
		white-space: nowrap;
	}
</style>
