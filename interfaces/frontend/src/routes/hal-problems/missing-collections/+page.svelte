<script lang="ts">
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page as pageStore } from '$app/stores';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { docTypeSingular } from '$lib/stores/docTypes';
	import { sanitizeTitle, halDocUrl } from '$lib/utils';
	import Pagination from '$lib/components/Pagination.svelte';

	import type { components } from '$lib/api/schema';
	type Lab = components['schemas']['HalCollectionLab'];
	type Pub = components['schemas']['HalMissingCollectionPub'];
	type Response = components['schemas']['HalMissingCollectionsResponse'];

	let labs: Lab[] = $state([]);
	let selectedLabId: number | null = $state(null);
	let pubs: Pub[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let loading = $state(false);
	let labAcronym = $state('');
	let halCollection = $state('');

	function syncUrl() {
		const p = new URLSearchParams();
		if (selectedLabId) p.set('lab_id', String(selectedLabId));
		if (page > 1) p.set('page', String(page));
		const qs = p.toString();
		replaceState(`${base}/hal-problems/missing-collections` + (qs ? '?' + qs : ''), {});
	}

	async function loadLabs() {
		labs = await api<Lab[]>('/api/hal-problems/missing-collections/labs');
		if (labs.length > 0 && !selectedLabId) {
			selectedLabId = labs[0].id;
		}
		loadPubs();
	}

	async function loadPubs() {
		if (!selectedLabId) return;
		loading = true;
		const data = await api<Response>(
			`/api/hal-problems/missing-collections?lab_id=${selectedLabId}&page=${page}&per_page=50`
		);
		pubs = data.publications;
		total = data.total;
		pages = data.pages;
		page = data.page;
		labAcronym = data.lab_acronym ?? '';
		halCollection = data.hal_collection;
		loading = false;
		syncUrl();
	}

	function onLabChange() {
		page = 1;
		loadPubs();
	}

	const halUrl = halDocUrl;

	onMount(() => {
		const urlParams = new URLSearchParams($pageStore.url.search);
		if (urlParams.get('lab_id')) selectedLabId = parseInt(urlParams.get('lab_id')!);
		if (urlParams.get('page')) page = parseInt(urlParams.get('page')!);
		loadLabs();
	});
</script>

<svelte:head>
	<title>Manques collections HAL — Bibliométrie UCA</title>
</svelte:head>

<h1>Manques collections HAL</h1>

<div class="info-box">
	Publications présentes dans OpenAlex ou WoS avec signature d'un labo UCA, et présentes dans HAL mais absentes de la collection HAL de ce labo.
</div>

<div class="toolbar">
	<select class="lab-select" bind:value={selectedLabId} onchange={onLabChange}>
		{#each labs as lab}
			<option value={lab.id}>{lab.acronym} — {lab.name} ({lab.hal_collection})</option>
		{/each}
	</select>
	<span class="count">{total} publication{total > 1 ? 's' : ''}</span>
</div>

{#if loading}
	<div class="loading">Chargement...</div>
{:else if pubs.length === 0 && selectedLabId}
	<div class="no-results">Aucune publication manquante pour {labAcronym} (collection {halCollection})</div>
{:else}
	<div class="pub-list">
		{#each pubs as pub}
			<div class="pub-card">
				<div class="pub-meta-line">
					{#if pub.pub_year}<span class="meta-badge">{pub.pub_year}</span>{/if}
					{#if pub.doc_type}<span class="meta-badge type-badge">{$docTypeSingular[pub.doc_type] || pub.doc_type}</span>{/if}
					{#if pub.hors_uca}<span class="badge-hors-uca">Hors collections UCA</span>{/if}
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
	<Pagination {page} {pages} onchange={(p) => { page = p; syncUrl(); loadPubs(); window.scrollTo(0, 0); }} />
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
	.pub-list { display: flex; flex-direction: column; gap: 8px; }
	.pub-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 10px 14px;
	}
	.pub-meta-line { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
	.meta-badge { flex-shrink: 0; }
	.badge-hors-uca {
		display: inline-block; padding: 1px 8px; background: #fff3e0;
		border: 1px solid #ffb74d; border-radius: 3px; font-size: 0.78rem;
		color: #e65100; font-weight: 600; flex-shrink: 0;
	}
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
