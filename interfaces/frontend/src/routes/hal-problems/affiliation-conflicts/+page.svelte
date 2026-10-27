<script lang="ts">
	import { institution } from '#lib/institution.svelte.js';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { withBase } from '#lib/paths.js';
	import { resolve } from '$app/paths';
	import { replaceQuery } from '#lib/url.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';

	import type { components } from '#lib/api/schema.js';
	type Pub = components['schemas']['HalAffiliationConflictPublication'];

	const list = usePaginatedFetch<Pub>({
		endpoint: '/api/hal-problems/affiliation-conflicts',
		itemsKey: 'publications',
		apiKey: 'hal-affiliation-conflicts',
		buildParams: () => new URLSearchParams(),
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (list.page > 1) p.set('page', String(list.page));
		void replaceQuery(resolve('hal-problems/affiliation-conflicts'), p);
	}


	onMount(() => {
		const urlParams = new URLSearchParams(page.url.search);
		if (urlParams.get('page')) list.page = parseInt(urlParams.get('page')!) || 1;
		list.load();
	});
</script>

<PageHeader title="Affiliations HAL divergentes">
	Publications affiliées à {institution.name} dans HAL mais pas dans une autre source. La publication est présente dans au moins une source non-HAL avec des adresses, mais sans signature {institution.name} à la même position d'auteur.
</PageHeader>

<ListToolbar {list} one="publication" many="publications" exportUrl={withBase('/api/hal-problems/affiliation-conflicts/export.csv')} />

<ListStatus {list} emptyText="Aucun conflit détecté">
	<div class="publication-list">
		{#each list.items as pub}
			<div class="publication-card">
				<div class="publication-meta-line">
					{#if pub.publication_year}<span class="meta-badge">{pub.publication_year}</span>{/if}
					{#if pub.doc_type}<DocTypePill docType={pub.doc_type} />{/if}
					{#each pub.laboratories as lab}<span class="meta-badge lab-badge" title={lab.name}>{structureLabel(lab)}</span>{/each}
					<a href={resolve(`publications/${pub.id}`)} class="publication-title"><PublicationTitle titre={pub.title} /></a>
				</div>
				<div class="hal-list">
					{#if pub.hal_links.length}
						{#each pub.hal_links as link (link.source_id)}
							<a href={link.record_url} target="_blank" rel="noopener" class="hal-link-badge">{link.source_id}</a>
						{/each}
					{/if}
					{#if pub.doi}
						<span class="doi-ref">DOI : <a href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a></span>
					{/if}
				</div>
			</div>
		{/each}
	</div>
	<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />
</ListStatus>

<style>
	.publication-list { display: flex; flex-direction: column; gap: 8px; }
	.publication-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 10px 14px;
	}
	.publication-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
	.meta-badge { flex-shrink: 0; }
	.lab-badge { background: var(--success-light); color: var(--success); font-weight: 500; }
	.hal-list {
		display: flex; flex-wrap: wrap; gap: 6px;
		align-items: center; margin-top: 6px; padding-left: 20px;
	}
	.doi-ref { font-size: 0.82rem; color: var(--muted); }
</style>
