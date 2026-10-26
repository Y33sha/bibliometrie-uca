<script lang="ts">
	import { pageTitle } from '#lib/institution.svelte.js';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import { resolve } from '$app/paths';
	import { replaceQuery } from '#lib/url.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { docTypeLabel } from '#lib/labels.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';

	import type { components } from '#lib/api/schema.js';
	type DoiPair = components['schemas']['HalDoiDuplicatePair'];
	type MetaPair = components['schemas']['HalMetaDuplicatePair'];

	let activeTab: 'doi' | 'meta' = $state('doi');

	const doi = usePaginatedFetch<DoiPair>({
		endpoint: '/api/hal-problems/duplicate-publications-doi',
		itemsKey: 'pairs',
		apiKey: 'hal-duplicate-publications-doi',
		pageParam: 'doi_page',
		buildParams: () => new URLSearchParams(),
	});

	const meta = usePaginatedFetch<MetaPair>({
		endpoint: '/api/hal-problems/duplicate-publications-meta',
		itemsKey: 'pairs',
		apiKey: 'hal-duplicate-publications-meta',
		pageParam: 'meta_page',
		buildParams: () => new URLSearchParams(),
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (activeTab !== 'doi') p.set('tab', activeTab);
		if (doi.page > 1) p.set('doi_page', String(doi.page));
		if (meta.page > 1) p.set('meta_page', String(meta.page));
		void replaceQuery(resolve('hal-problems/duplicate-publications'), p);
	}

	function switchTab(tab: 'doi' | 'meta') {
		activeTab = tab;
		if (tab === 'doi' && doi.items.length === 0) doi.load();
		if (tab === 'meta' && meta.items.length === 0) meta.load();
		syncUrl();
	}


	onMount(() => {
		const urlParams = new URLSearchParams(page.url.search);
		if (urlParams.get('tab')) activeTab = urlParams.get('tab') as 'doi' | 'meta';
		if (urlParams.get('doi_page')) doi.page = parseInt(urlParams.get('doi_page')!) || 1;
		if (urlParams.get('meta_page')) meta.page = parseInt(urlParams.get('meta_page')!) || 1;
		if (activeTab === 'meta') meta.load();
		doi.load();
	});
</script>

<svelte:head>
	<title>{pageTitle("Doublons publis HAL")}</title>
</svelte:head>

<h1>Doublons de publications HAL</h1>

<div class="info-box">
	{#if activeTab === 'doi'}
		Dépôts HAL avec DOI identique. Soit dépôts en doublon, soit DOI erroné.
	{:else}
		Doublons possibles : dépôts HAL avec titre, année, type et nombre d'auteurs cohérents.
	{/if}
</div>

<div class="tabs">
	<button class="tab" class:active={activeTab === 'doi'} onclick={() => switchTab('doi')}>
		Par DOI{doi.items.length ? ` (${doi.total})` : ''}
	</button>
	<button class="tab" class:active={activeTab === 'meta'} onclick={() => switchTab('meta')}>
		Par métadonnées{meta.items.length ? ` (${meta.total})` : ''}
	</button>
</div>

{#if activeTab === 'doi'}
	<ListStatus list={doi} emptyText="Aucun doublon par DOI">
		<div class="doi-list">
			{#each doi.items as pair}
				<div class="doi-card">
					<div class="publication-meta-line">
						{#if pair.publication.publication_year}<span class="meta-badge">{pair.publication.publication_year}</span>{/if}
						{#if pair.publication.doc_type}<DocTypePill docType={pair.publication.doc_type} />{/if}
						<a href={resolve(`publications/${pair.publication.id}`)} class="publication-title"><PublicationTitle titre={pair.publication.title} /></a>
					</div>
					<div class="hal-list">
						{#each pair.publication.hal_docs as hd}
							<div class="hal-row">
								<a href={hd.record_url} target="_blank" rel="noopener" class="hal-link-badge">{hd.halid}</a>
								{#if hd.hal_publication_year}<span class="meta-badge">{hd.hal_publication_year}</span>{/if}
								{#if hd.hal_doc_type}<span class="meta-badge type-badge">{docTypeLabel(hd.hal_doc_type)}</span>{/if}
								<span class="author-count">{hd.author_count} aut.</span>
							</div>
						{/each}
						<span class="doi-ref">DOI : <a href="https://doi.org/{pair.doi}" target="_blank" rel="noopener">{pair.doi}</a></span>
					</div>
				</div>
			{/each}
		</div>
		<Pagination page={doi.page} pages={doi.pages} onchange={(p) => { doi.goToPage(p); syncUrl(); }} />
	</ListStatus>

{:else}
	<ListStatus list={meta} emptyText="Aucun doublon par métadonnées">
		<table class="data-table meta-table">
			<thead>
				<tr>
					<th>Publication A</th>
					<th>Publication B</th>
				</tr>
			</thead>
			<tbody>
				{#each meta.items as pair}
					<tr>
						{#each [pair.publication_a, pair.publication_b] as pub}
							<td>
								<a href={resolve(`publications/${pub.id}`)} class="publication-title"><PublicationTitle titre={pub.title} /></a>
								<div class="publication-meta-line">
									{#if pub.publication_year}<span class="meta-badge">{pub.publication_year}</span>{/if}
									{#if pub.doc_type}<DocTypePill docType={pub.doc_type} />{/if}
									{#if pub.doi}<span class="meta-badge">DOI</span>{/if}
								</div>
								<div class="hal-list">
									{#each pub.hal_docs as hd}
										<div class="hal-row">
											<a href={hd.record_url} target="_blank" rel="noopener" class="hal-link-badge">{hd.halid}</a>
											{#if hd.hal_publication_year}<span class="meta-badge">{hd.hal_publication_year}</span>{/if}
											{#if hd.hal_doc_type}<span class="meta-badge type-badge">{docTypeLabel(hd.hal_doc_type)}</span>{/if}
											<span class="author-count">{hd.author_count} aut.</span>
										</div>
									{/each}
								</div>
								{#if pub.container_title}
									<div class="container-title">{pub.container_title}</div>
								{/if}
							</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
		<Pagination page={meta.page} pages={meta.pages} onchange={(p) => { meta.goToPage(p); syncUrl(); }} />
	</ListStatus>
{/if}

<style>
	.data-table td { font-size: 0.9rem; }
	.meta-table td { width: 50%; }

	.doi-list { display: flex; flex-direction: column; gap: 8px; }
	.doi-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: var(--radius);
		padding: 10px 14px;
	}
	.hal-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; padding-left: 20px; }
	.hal-row { display: flex; gap: 6px; align-items: center; }
	.doi-ref { font-size: 0.82rem; color: var(--muted); margin-left: 8px; }
	.publication-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 3px; }
	.author-count { font-size: 0.8rem; color: var(--muted); }
	.container-title { font-size: 0.82rem; color: var(--muted); margin-top: 2px; font-style: italic; }
</style>
