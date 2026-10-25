<script lang="ts">
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { apiDetail } from '#lib/api/index.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import { titleText } from '#lib/utils.js';
	import type { components } from '#lib/api/schema.js';

	type Monograph = components['schemas']['MonographListItem'];

	const monographId = $derived(Number(page.params.id));

	let monograph = $state<Monograph | null>(null);
	let error = $state(false);
	onMount(async () => {
		try {
			monograph = await apiDetail<Monograph>(`/api/monographs/${monographId}`);
		} catch {
			error = true;
		}
	});
</script>

<svelte:head>
	<title>{pageTitle(titleText(monograph?.title) || 'Monographie')}</title>
</svelte:head>

	<Breadcrumb trail={[{ label: 'Monographies', path: 'monographs' }]} current={titleText(monograph?.title)} />

{#if error}
	<div class="no-results">Monographie introuvable</div>
{:else if !monograph}
	<div class="loading">Chargement…</div>
{:else}
	<div class="entity-header">
		<h1 class="entity-title"><PublicationTitle titre={monograph.title} /></h1>
		<div class="entity-meta">
			<span class="entity-tag">{monograph.proceedings ? "Volume d'actes" : 'Livre'}</span>
			{#if monograph.year}
				<span class="entity-meta-label">Année</span>
				<span>{monograph.year}</span>
			{/if}
			{#if monograph.isbn}
				<span class="entity-meta-label">ISBN</span>
				<span class="id-badge">{monograph.isbn}</span>
			{/if}
			{#if monograph.eisbn}
				<span class="entity-meta-label">ISBN électronique</span>
				<span class="id-badge">{monograph.eisbn}</span>
			{/if}
		</div>
		<div class="entity-meta">
			{#if monograph.publisher_id}
				<span class="entity-meta-label">Éditeur</span>
				<a href={resolve(`publishers/${monograph.publisher_id}`)}>{monograph.publisher_name}</a>
			{/if}
			{#if monograph.serial_id}
				<span class="entity-meta-label">Collection</span>
				<a href={resolve(`journals/${monograph.serial_id}`)}>{monograph.journal_title}</a>
			{/if}
		</div>
	</div>

	<div class="m-publications">
		<PublicationsListView
			apiKey={`monograph-${monographId}-publications`}
			externalFilters={{ monographId }}
			basePath={`/monographs/${monographId}`}
			showFilterBanner={false}
			perPage={50}
		/>
	</div>
{/if}

<style>
	.m-publications { margin-top: 28px; }
	.loading, .no-results { padding: 20px; color: var(--muted); }
</style>
