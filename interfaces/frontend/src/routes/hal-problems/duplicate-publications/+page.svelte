<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import { horizontalOverflow } from '#lib/actions/horizontalOverflow.js';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import { withBase } from '#lib/paths.js';
	import DocTypePill from '#lib/components/DocTypePill.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import { resolve } from '$app/paths';
	import { replaceQuery } from '#lib/url.js';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { columnLabels, docTypeLabel } from '#lib/labels.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';

	import type { components } from '#lib/api/schema.js';
	type DoiPair = components['schemas']['HalDoiDuplicatePair'];
	type MetaPair = components['schemas']['HalMetaDuplicatePair'];
	type HalDoc = components['schemas']['HalDocSummary'];

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

<PageHeader title="Dépôts HAL en double">
	{#if activeTab === 'doi'}
		Dépôts HAL avec DOI identique. Soit dépôts en doublon, soit DOI erroné.
	{:else}
		Doublons possibles : dépôts HAL avec titre, année, type et nombre d'auteurs cohérents.
	{/if}
</PageHeader>

<div class="tabs" use:horizontalOverflow>
	<button class="tab" class:active={activeTab === 'doi'} onclick={() => switchTab('doi')}>
		Par DOI{doi.items.length ? ` (${doi.total})` : ''}
	</button>
	<button class="tab" class:active={activeTab === 'meta'} onclick={() => switchTab('meta')}>
		Par métadonnées{meta.items.length ? ` (${meta.total})` : ''}
	</button>
</div>

<ListToolbar
	list={activeTab === 'doi' ? doi : meta}
	one={activeTab === 'doi' ? 'DOI' : 'paire'}
	many={activeTab === 'doi' ? 'DOI' : 'paires'}
	exportUrl={withBase(`/api/hal-problems/duplicate-publications-${activeTab}/export.csv`)}
/>

{#if activeTab === 'doi'}
	<ListStatus list={doi} emptyText="Aucun doublon par DOI">
		<TableScroll>
			<table class="data-table">
				<thead>
					<tr>
						<th>{columnLabels.type}</th>
						<th>{columnLabels.year}</th>
						<th>{columnLabels.doi}</th>
						<th>{columnLabels.title}</th>
						<th>Dépôts HAL</th>
					</tr>
				</thead>
				<tbody>
					{#each doi.items as pair (`${pair.publication.id}:${pair.doi}`)}
						<tr>
							<td>{#if pair.publication.doc_type}<DocTypePill docType={pair.publication.doc_type} />{/if}</td>
							<td>{pair.publication.publication_year ?? ''}</td>
							<td><DoiLink doi={pair.doi} /></td>
							<td><a href={resolve(`publications/${pair.publication.id}`)} class="publication-title"><PublicationTitle titre={pair.publication.title} /></a></td>
							<td>
								<div class="hal-list">
									{#each pair.publication.hal_docs as hd (hd.halid)}{@render halDoc(hd)}{/each}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</TableScroll>
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
									{#each pub.hal_docs as hd (hd.halid)}{@render halDoc(hd)}{/each}
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

<!-- Un dépôt HAL : son identifiant, puis l'année, le type et le nombre d'auteurs que HAL lui donne. -->
{#snippet halDoc(hd: HalDoc)}
	<div class="hal-row">
		<a href={hd.record_url} target="_blank" rel="noopener" class="id-badge">{hd.halid}</a>
		<span class="hal-details">{[hd.hal_publication_year, hd.hal_doc_type ? docTypeLabel(hd.hal_doc_type) : null, `${hd.author_count} auteur${hd.author_count > 1 ? 's' : ''}`].filter(Boolean).join(' · ')}</span>
	</div>
{/snippet}

<style>
	.data-table td { font-size: 0.9rem; }
	.meta-table td { width: 50%; }

	.hal-list { display: flex; flex-direction: column; gap: 4px; }
	.meta-table .hal-list { margin-top: 6px; }
	.hal-row { display: flex; gap: 8px; align-items: center; white-space: nowrap; }
	.publication-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 3px; }
	.hal-details { font-size: 0.8rem; color: var(--text-secondary); }
	.container-title { font-size: 0.82rem; color: var(--muted); margin-top: 2px; font-style: italic; }
</style>
