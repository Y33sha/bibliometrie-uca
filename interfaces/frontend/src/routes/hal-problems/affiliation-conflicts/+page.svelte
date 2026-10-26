<script lang="ts">
	import { institution, pageTitle } from '#lib/institution.svelte.js';
	import ResultCount from '#lib/components/ResultCount.svelte';
	import { resolve } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { docTypeSingular, docTypeColor } from '#lib/labels.js';
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
		const qs = p.toString();
		replaceState(resolve('hal-problems/affiliation-conflicts') + (qs ? '?' + qs : ''), {});
	}


	onMount(() => {
		const urlParams = new URLSearchParams(page.url.search);
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
	<ResultCount {list} one="publication" many="publications" />
</div>

<ListStatus {list} emptyText="Aucun conflit détecté">
	<div class="publication-list">
		{#each list.items as pub}
			<div class="publication-card">
				<div class="publication-meta-line">
					{#if pub.publication_year}<span class="meta-badge">{pub.publication_year}</span>{/if}
					{#if pub.doc_type}<span class="type-pill" style="--type-color: {docTypeColor(pub.doc_type)}">{docTypeSingular[pub.doc_type] || pub.doc_type}</span>{/if}
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
