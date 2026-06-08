<script lang="ts">
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page as pageStore } from '$app/stores';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { docTypeSingular } from '$lib/labels';
	import { sanitizeTitle, halDocUrl } from '$lib/utils';
	import Pagination from '$lib/components/Pagination.svelte';

	import type { components } from '$lib/api/schema';
	type Pub = components['schemas']['HalAffiliationConflictPub'];
	type Response = components['schemas']['HalAffiliationConflictsResponse'];

	let pubs: Pub[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let loading = $state(false);

	function syncUrl() {
		const p = new URLSearchParams();
		if (page > 1) p.set('page', String(page));
		const qs = p.toString();
		replaceState(`${base}/hal-problems/affiliation-conflicts` + (qs ? '?' + qs : ''), {});
	}

	async function load() {
		loading = true;
		const data = await api<Response>(
			`/api/hal-problems/affiliation-conflicts?page=${page}&per_page=50`
		);
		pubs = data.publications;
		total = data.total;
		pages = data.pages;
		page = data.page;
		loading = false;
		syncUrl();
	}

	const halUrl = halDocUrl;

	onMount(() => {
		const urlParams = new URLSearchParams($pageStore.url.search);
		if (urlParams.get('page')) page = parseInt(urlParams.get('page')!);
		load();
	});
</script>

<svelte:head>
	<title>Conflits d'affiliations HAL — Bibliométrie UCA</title>
</svelte:head>

<h1>Conflits d'affiliations HAL</h1>

<div class="info-box">
	Publications affiliées UCA dans HAL mais pas dans une autre source. La publication est présente dans au moins une source non-HAL avec des adresses, mais sans signature UCA à la même position d'auteur.
</div>

<div class="toolbar">
	<span class="count">{total} publication{total > 1 ? 's' : ''}</span>
</div>

{#if loading}
	<div class="loading">Chargement...</div>
{:else if pubs.length === 0}
	<div class="no-results">Aucun conflit détecté</div>
{:else}
	<div class="pub-list">
		{#each pubs as pub}
			<div class="pub-card">
				<div class="pub-meta-line">
					{#if pub.pub_year}<span class="meta-badge">{pub.pub_year}</span>{/if}
					{#if pub.doc_type}<span class="meta-badge type-badge">{docTypeSingular[pub.doc_type] || pub.doc_type}</span>{/if}
					{#if pub.labs}<span class="meta-badge lab-badge">{pub.labs}</span>{/if}
					<a href="{base}/publications/{pub.id}" class="pub-link">{@html sanitizeTitle(pub.title)}</a>
				</div>
				<div class="hal-list">
					{#if pub.halids}
						{#each pub.halids as halid}
							<a href={halUrl(halid)} target="_blank" rel="noopener" class="hal-badge">{halid}</a>
						{/each}
					{/if}
					{#if pub.doi}
						<span class="doi-ref">DOI : <a href="https://doi.org/{pub.doi}" target="_blank" rel="noopener">{pub.doi}</a></span>
					{/if}
				</div>
			</div>
		{/each}
	</div>
	<Pagination {page} {pages} onchange={(p) => { page = p; syncUrl(); load(); window.scrollTo(0, 0); }} />
{/if}

<style>
	.count { font-size: 0.9rem; }
	.pub-list { display: flex; flex-direction: column; gap: 8px; }
	.pub-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 10px 14px;
	}
	.pub-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
	.meta-badge { flex-shrink: 0; }
	.lab-badge { background: var(--success-light); color: var(--success); font-weight: 500; }
	.pub-link { color: var(--accent); text-decoration: none; font-weight: 500; font-size: 0.88rem; }
	.pub-link:hover { text-decoration: underline; }
	.hal-list {
		display: flex; flex-wrap: wrap; gap: 6px;
		align-items: center; margin-top: 6px; padding-left: 20px;
	}
	.hal-badge {
		display: inline-block; padding: 2px 8px; background: #1a6fb5;
		border-radius: 4px; font-size: 0.82rem; color: #fff;
		text-decoration: none; font-weight: 500;
	}
	.hal-badge:hover { background: #145a94; }
	.doi-ref { font-size: 0.82rem; color: var(--muted); }
	.doi-ref a { color: var(--accent); text-decoration: none; }
	.doi-ref a:hover { text-decoration: underline; }
</style>
