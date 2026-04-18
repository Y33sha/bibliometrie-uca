<script lang="ts">
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page as pageStore } from '$app/stores';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { typeLabels } from '$lib/labels';
	import { sanitizeTitle, halDocUrl } from '$lib/utils';
	import Pagination from '$lib/components/Pagination.svelte';

	interface HalDoc {
		halid: string;
		collections: string[] | null;
		author_count: number;
		hal_doc_type: string | null;
		hal_pub_year: number | null;
		hal_title: string | null;
	}
	interface PubDetail {
		id: number;
		title: string;
		pub_year: number | null;
		doc_type: string | null;
		doi: string | null;
		container_title: string | null;
		hal_docs: HalDoc[];
	}
	interface DoiPair { doi: string; halids: string[]; publication: PubDetail }
	interface MetaPair { pub_a: PubDetail; pub_b: PubDetail }
	interface DoiResponse { total: number; page: number; pages: number; pairs: DoiPair[] }
	interface MetaResponse { total: number; page: number; pages: number; pairs: MetaPair[] }

	let activeTab: 'doi' | 'meta' = $state('doi');

	let doiPairs: DoiPair[] = $state([]);
	let doiTotal = $state(0);
	let doiPage = $state(1);
	let doiPages = $state(1);
	let doiLoading = $state(false);

	let metaPairs: MetaPair[] = $state([]);
	let metaTotal = $state(0);
	let metaPage = $state(1);
	let metaPages = $state(1);
	let metaLoading = $state(false);

	async function loadDoi() {
		doiLoading = true;
		const data = await api<DoiResponse>(`/api/hal-problems/duplicate-pubs-doi?page=${doiPage}&per_page=50`);
		doiPairs = data.pairs;
		doiTotal = data.total;
		doiPages = data.pages;
		doiPage = data.page;
		doiLoading = false;
		syncUrl();
	}

	async function loadMeta() {
		metaLoading = true;
		const data = await api<MetaResponse>(`/api/hal-problems/duplicate-pubs-meta?page=${metaPage}&per_page=50`);
		metaPairs = data.pairs;
		metaTotal = data.total;
		metaPages = data.pages;
		metaPage = data.page;
		metaLoading = false;
		syncUrl();
	}

	function syncUrl() {
		const p = new URLSearchParams();
		if (activeTab !== 'doi') p.set('tab', activeTab);
		if (doiPage > 1) p.set('doi_page', String(doiPage));
		if (metaPage > 1) p.set('meta_page', String(metaPage));
		const qs = p.toString();
		replaceState(`${base}/hal-problems/duplicate-pubs` + (qs ? '?' + qs : ''), {});
	}

	function switchTab(tab: 'doi' | 'meta') {
		activeTab = tab;
		if (tab === 'doi' && doiPairs.length === 0) loadDoi();
		if (tab === 'meta' && metaPairs.length === 0) loadMeta();
		syncUrl();
	}

	const halUrl = halDocUrl;

	onMount(() => {
		const urlParams = new URLSearchParams($pageStore.url.search);
		if (urlParams.get('tab')) activeTab = urlParams.get('tab') as 'doi' | 'meta';
		if (urlParams.get('doi_page')) doiPage = parseInt(urlParams.get('doi_page')!);
		if (urlParams.get('meta_page')) metaPage = parseInt(urlParams.get('meta_page')!);
		if (activeTab === 'meta') {
			loadMeta();
			loadDoi();
		} else {
			loadDoi();
		}
	});
</script>

<svelte:head>
	<title>Doublons publis HAL — Bibliométrie UCA</title>
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
		Par DOI{doiPairs.length || doiLoading ? ` (${doiTotal})` : ''}
	</button>
	<button class="tab" class:active={activeTab === 'meta'} onclick={() => switchTab('meta')}>
		Par métadonnées{metaPairs.length || metaLoading ? ` (${metaTotal})` : ''}
	</button>
</div>

{#if activeTab === 'doi'}
	{#if doiLoading}
		<div class="loading">Chargement...</div>
	{:else if doiPairs.length === 0}
		<div class="no-results">Aucun doublon par DOI</div>
	{:else}
		<div class="doi-list">
			{#each doiPairs as pair}
				<div class="doi-card">
					<div class="pub-meta-line">
						{#if pair.publication.pub_year}<span class="meta-badge">{pair.publication.pub_year}</span>{/if}
						{#if pair.publication.doc_type}<span class="meta-badge type-badge">{typeLabels[pair.publication.doc_type] || pair.publication.doc_type}</span>{/if}
						<a href="{base}/publications/{pair.publication.id}" class="pub-link">{@html sanitizeTitle(pair.publication.title)}</a>
					</div>
					<div class="hal-list">
						{#each pair.publication.hal_docs as hd}
							<div class="hal-row">
								<a href={halUrl(hd.halid)} target="_blank" rel="noopener" class="hal-badge">{hd.halid}</a>
								{#if hd.hal_pub_year}<span class="meta-badge">{hd.hal_pub_year}</span>{/if}
								{#if hd.hal_doc_type}<span class="meta-badge type-badge">{hd.hal_doc_type}</span>{/if}
								<span class="author-count">{hd.author_count} aut.</span>
							</div>
						{/each}
						<span class="doi-ref">DOI : <a href="https://doi.org/{pair.doi}" target="_blank" rel="noopener">{pair.doi}</a></span>
					</div>
				</div>
			{/each}
		</div>
		<Pagination page={doiPage} pages={doiPages} onchange={(p) => { doiPage = p; syncUrl(); loadDoi(); window.scrollTo(0, 0); }} />
	{/if}

{:else}
	{#if metaLoading}
		<div class="loading">Chargement...</div>
	{:else if metaPairs.length === 0}
		<div class="no-results">Aucun doublon par métadonnées</div>
	{:else}
		<table class="pub-table meta-table">
			<thead>
				<tr>
					<th>Publication A</th>
					<th>Publication B</th>
				</tr>
			</thead>
			<tbody>
				{#each metaPairs as pair}
					<tr>
						{#each [pair.pub_a, pair.pub_b] as pub}
							<td>
								<a href="{base}/publications/{pub.id}" class="pub-link">{@html sanitizeTitle(pub.title)}</a>
								<div class="pub-meta-line">
									{#if pub.pub_year}<span class="meta-badge">{pub.pub_year}</span>{/if}
									{#if pub.doc_type}<span class="meta-badge type-badge">{typeLabels[pub.doc_type] || pub.doc_type}</span>{/if}
									{#if pub.doi}<span class="meta-badge">DOI</span>{/if}
								</div>
								<div class="hal-list">
									{#each pub.hal_docs as hd}
										<div class="hal-row">
											<a href={halUrl(hd.halid)} target="_blank" rel="noopener" class="hal-badge">{hd.halid}</a>
											{#if hd.hal_pub_year}<span class="meta-badge">{hd.hal_pub_year}</span>{/if}
											{#if hd.hal_doc_type}<span class="meta-badge type-badge">{hd.hal_doc_type}</span>{/if}
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
		<Pagination page={metaPage} pages={metaPages} onchange={(p) => { metaPage = p; syncUrl(); loadMeta(); window.scrollTo(0, 0); }} />
	{/if}
{/if}

<style>
	/* Override tabs for this page: underline variant */
	.tabs {
		background: none;
		border-left: none;
		border-right: none;
		border-bottom: 2px solid var(--border);
		border-radius: 0;
	}
	.tab {
		flex: none;
		padding: 8px 16px;
		background: none;
		border-right: none;
		border-bottom: 2px solid transparent;
		margin-bottom: -2px;
	}
	.tab.active { box-shadow: none; border-bottom-color: var(--accent); }

	.pub-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.pub-table thead th {
		background: #f5f4f1; padding: 8px 12px; text-align: left;
		font-size: 0.85rem; font-weight: 600; color: var(--muted);
		border-bottom: 2px solid var(--border);
	}
	.pub-table tbody tr { border-bottom: 1px solid #f0efec; }
	.pub-table tbody tr:hover { background: #fafaf8; }
	.pub-table td { padding: 8px 12px; font-size: 0.9rem; vertical-align: top; }
	.meta-table td { width: 50%; }

	.doi-list { display: flex; flex-direction: column; gap: 8px; }
	.doi-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 10px 14px;
	}
	.hal-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; padding-left: 20px; }
	.hal-row { display: flex; gap: 6px; align-items: center; }
	.doi-ref { font-size: 0.82rem; color: var(--muted); margin-left: 8px; }
	.doi-ref a { color: var(--accent); text-decoration: none; }
	.doi-ref a:hover { text-decoration: underline; }
	.pub-link { color: var(--accent); text-decoration: none; font-weight: 500; font-size: 0.88rem; }
	.pub-link:hover { text-decoration: underline; }
	.pub-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 3px; }
	.hal-badge {
		display: inline-block; padding: 2px 8px; background: #1a6fb5;
		border-radius: 4px; font-size: 0.82rem; color: #fff;
		text-decoration: none; font-weight: 500;
	}
	.hal-badge:hover { background: #145a94; }
	.author-count { font-size: 0.8rem; color: var(--muted); }
	.container-title { font-size: 0.82rem; color: var(--muted); margin-top: 2px; font-style: italic; }
</style>
