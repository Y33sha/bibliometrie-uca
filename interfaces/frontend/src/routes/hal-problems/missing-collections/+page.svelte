<script lang="ts">
	import { institution, pageTitle } from '#lib/institution.svelte.js';
	import { resolve } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { api } from '#lib/api/index.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { docTypeSingular } from '#lib/labels.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import Pagination from '#lib/components/Pagination.svelte';

	import type { components } from '#lib/api/schema.js';
	type Lab = components['schemas']['HalCollectionLab'];
	type Pub = components['schemas']['HalMissingCollectionPublication'];

	let labs: Lab[] = $state([]);
	let labsLoaded = $state(false);
	let selectedLabId: number | null = $state(null);
	const selectedLab = $derived(labs.find((lab) => lab.id === selectedLabId));

	const list = usePaginatedFetch<Pub>({
		endpoint: '/api/hal-problems/missing-collections',
		itemsKey: 'publications',
		apiKey: 'hal-missing-collections',
		buildParams() {
			const params = new URLSearchParams();
			if (selectedLabId) params.set('lab_id', String(selectedLabId));
			return params;
		},
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (selectedLabId) p.set('lab_id', String(selectedLabId));
		if (list.page > 1) p.set('page', String(list.page));
		const qs = p.toString();
		replaceState(resolve('hal-problems/missing-collections') + (qs ? '?' + qs : ''), {});
	}

	async function loadLabs() {
		labs = await api<Lab[]>('/api/hal-problems/missing-collections/labs');
		if (labs.length > 0 && !selectedLabId) {
			selectedLabId = labs[0].id;
		}
		labsLoaded = true;
		if (!selectedLabId) return;
		await list.load();
		syncUrl();
	}

	function onLabChange() {
		list.page = 1;
		syncUrl();
		list.load();
	}


	onMount(() => {
		const urlParams = new URLSearchParams(page.url.search);
		if (urlParams.get('lab_id')) selectedLabId = parseInt(urlParams.get('lab_id')!);
		if (urlParams.get('page')) list.page = parseInt(urlParams.get('page')!) || 1;
		loadLabs();
	});
</script>

<svelte:head>
	<title>{pageTitle("Manques collections HAL")}</title>
</svelte:head>

<h1>Manques collections HAL</h1>

<div class="info-box">
	Publications présentes dans OpenAlex ou WoS avec signature d'un labo {institution.name}, et présentes dans HAL mais absentes de la collection HAL de ce labo.
</div>

<div class="toolbar">
	<select class="lab-select" bind:value={selectedLabId} onchange={onLabChange}>
		{#each labs as lab}
			<option value={lab.id}>{lab.acronym} — {lab.name} ({lab.hal_collection})</option>
		{/each}
	</select>
	<span class="count">{list.total} publication{list.total > 1 ? 's' : ''}</span>
</div>

{#if !labsLoaded || (selectedLabId && list.loading)}
	<div class="loading">Chargement…</div>
{:else if list.items.length === 0 && selectedLabId}
	<div class="no-results">Aucune publication manquante pour {selectedLab?.acronym ?? ''} (collection {selectedLab?.hal_collection ?? ''})</div>
{:else}
	<div class="publication-list">
		{#each list.items as pub}
			<div class="publication-card">
				<div class="publication-meta-line">
					{#if pub.publication_year}<span class="meta-badge">{pub.publication_year}</span>{/if}
					{#if pub.doc_type}<span class="meta-badge type-badge">{docTypeSingular[pub.doc_type] || pub.doc_type}</span>{/if}
					{#if pub.outside_perimeter_collections}<span class="badge-hors-uca">Hors collections de l'établissement</span>{/if}
					<a href={resolve(`publications/${pub.id}`)} class="publication-link"><PublicationTitle titre={pub.title} /></a>
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
{/if}

<style>
	.lab-select {
		padding: 6px 10px;
		border: 2px solid var(--accent);
		border-radius: 4px;
		font-size: 0.9rem;
		font-family: inherit;
		font-weight: 600;
		color: var(--accent);
		min-width: 300px;
	}
	.count { font-size: 0.9rem; }
	.publication-list { display: flex; flex-direction: column; gap: 8px; }
	.publication-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 10px 14px;
	}
	.publication-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
	.meta-badge { flex-shrink: 0; }
	.badge-hors-uca {
		display: inline-block; padding: 1px 8px; background: var(--attention-light);
		border: 1px solid color-mix(in srgb, var(--attention) 40%, white); border-radius: 3px; font-size: 0.78rem;
		color: var(--attention); font-weight: 600; flex-shrink: 0;
	}
	.publication-link { color: var(--accent); text-decoration: none; font-weight: 500; font-size: 0.88rem; }
	.publication-link:hover { text-decoration: underline; }
	.hal-list {
		display: flex; flex-wrap: wrap; gap: 6px;
		align-items: center; margin-top: 6px; padding-left: 20px;
	}
	.doi-ref { font-size: 0.82rem; color: var(--muted); }
</style>
