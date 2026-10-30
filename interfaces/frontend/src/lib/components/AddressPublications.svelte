<script lang="ts">
	import { resolve } from '$app/paths';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import { docTypeLabel } from '#lib/docTypes.svelte.js';
	import type { components } from '#lib/api/schema.js';

	type Publication = components['schemas']['AddressPublicationItem'];

	/** Publications liées à une adresse, sous la ligne de l'adresse dépliée. */
	let { publications, loading }: { publications: Publication[]; loading: boolean } = $props();
</script>

{#if loading}
	<div class="detail-loading">Chargement…</div>
{:else if publications.length === 0}
	<div class="detail-loading">Aucune publication liée.</div>
{:else}
	{#each publications as p (p.id)}
		<div class="publication-row">
			<a href={resolve(`publications/${p.id}`)} class="publication-title-link">
				<PublicationTitle titre={p.title || '(sans titre)'} />
			</a>
			<div class="publication-meta-inline">
				{p.publication_year}
				{#if p.doc_type}&middot; {docTypeLabel(p.doc_type)}{/if}
				{#if p.author_name}&middot; {p.author_name}{/if}
				{#if p.journal_title}&middot; {p.journal_title}{/if}
				{#if p.doi}<span class="publication-doi"><DoiLink doi={p.doi} /></span>{/if}
			</div>
		</div>
	{/each}
{/if}

<style>
	.detail-loading {
		padding: 8px;
		color: var(--muted);
	}
	.publication-row {
		padding: 5px 0;
		border-bottom: 1px solid var(--border-subtle);
		font-size: var(--fs-sm);
	}
	.publication-row:last-child {
		border-bottom: none;
	}
	.publication-title-link {
		display: block;
		font-weight: 500;
	}
	.publication-meta-inline {
		font-size: var(--fs-sm);
		color: var(--muted);
		margin-top: 2px;
	}
	.publication-doi {
		margin-left: 6px;
	}
</style>
