<script lang="ts">
	import { base } from '$app/paths';

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
			<a
				class="id-icon id-orcid"
				class:id-confirmed={id.confirmed}
				href="https://orcid.org/{id.value}"
				target="_blank"
				rel="noopener"
				title="ORCID : {id.value}"
			>
				<img src="{base}/icons/orcid.ico" alt="ORCID" />
			</a>
		{/each}
	{:else}
		<span class="id-icon id-placeholder"></span>
	{/if}

	{#if idhals && idhals.length}
		{#each idhals as id (id.value)}
			<a
				class="id-icon id-hal"
				class:id-confirmed={id.confirmed}
				href="https://hal.science/search/index/?q=%2A&authIdHal_s={id.value}"
				target="_blank"
				rel="noopener"
				title="idHAL : {id.value}"
			>
				<img src="{base}/icons/hal.ico" alt="idHAL" />
			</a>
		{/each}
	{:else}
		<span class="id-icon id-placeholder"></span>
	{/if}

	{#if idrefs && idrefs.length}
		{#each idrefs as id (id.value)}
			<a
				class="id-icon id-idref"
				class:id-confirmed={id.confirmed}
				href="https://www.idref.fr/{id.value}"
				target="_blank"
				rel="noopener"
				title="IdRef : {id.value}"
			>
				<img src="{base}/icons/idref.png" alt="IdRef" />
			</a>
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
