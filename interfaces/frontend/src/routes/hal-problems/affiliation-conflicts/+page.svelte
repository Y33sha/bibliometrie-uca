<script lang="ts">
	import { institution, pageTitle } from '$lib/institution.svelte';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page as pageStore } from '$app/stores';
	import { onMount } from 'svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import { docTypeSingular } from '$lib/labels';
	import { halDocUrl } from '$lib/utils';
	import PublicationTitle from '$lib/components/PublicationTitle.svelte';
	import Pagination from '$lib/components/Pagination.svelte';

	import type { components } from '$lib/api/schema';
	type Pub = components['schemas']['HalAffiliationConflictPub'];

	const list = usePaginatedFetch<Pub>({
		endpoint: '/api/hal-problems/affiliation-conflicts',
		itemsKey: 'publications',
		apiKey: 'hal-affiliation-conflicts',
		buildParams: () => new URLSearchParams(),
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (list.page > 1) p.set('page', String(list.page));
		const qs = p.toString();
		replaceState(`${base}/hal-problems/affiliation-conflicts` + (qs ? '?' + qs : ''), {});
	}

	const halUrl = halDocUrl;

	onMount(() => {
		const urlParams = new URLSearchParams($pageStore.url.search);
		if (urlParams.get('page')) list.page = parseInt(urlParams.get('page')!) || 1;
		list.load();
	});
</script>

<svelte:head>
	<title>{pageTitle("Conflits d'affiliations HAL")}</title>
</svelte:head>

<h1>Conflits d'affiliations HAL</h1>

<div class="info-box">
	Publications affiliées à {institution.name} dans HAL mais pas dans une autre source. La publication est présente dans au moins une source non-HAL avec des adresses, mais sans signature {institution.name} à la même position d'auteur.
</div>

<div class="toolbar">
	<span class="count">{list.total} publication{list.total > 1 ? 's' : ''}</span>
</div>

{#if list.loading}
	<div class="loading">Chargement…</div>
{:else if list.items.length === 0}
	<div class="no-results">Aucun conflit détecté</div>
{:else}
	<div class="pub-list">
		{#each list.items as pub}
			<div class="pub-card">
				<div class="pub-meta-line">
					{#if pub.pub_year}<span class="meta-badge">{pub.pub_year}</span>{/if}
					{#if pub.doc_type}<span class="meta-badge type-badge">{docTypeSingular[pub.doc_type] || pub.doc_type}</span>{/if}
					{#each pub.laboratories as lab}<span class="meta-badge lab-badge" title={lab.name}>{lab.acronym || lab.name}</span>{/each}
					<a href="{base}/publications/{pub.id}" class="pub-link"><PublicationTitle titre={pub.title} /></a>
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
	<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />
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
</style>
