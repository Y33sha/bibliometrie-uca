<script lang="ts">
	import EntityMetaItem from '#lib/components/EntityMetaItem.svelte';
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
				<EntityMetaItem label="Année"><span>{monograph.year}</span></EntityMetaItem>
			{/if}
			{#if monograph.isbn}
				<EntityMetaItem label="ISBN"><span class="id-badge">{monograph.isbn}</span></EntityMetaItem>
			{/if}
			{#if monograph.eisbn}
				<EntityMetaItem label="ISBN électronique"><span class="id-badge">{monograph.eisbn}</span></EntityMetaItem>
			{/if}
		</div>
		<div class="entity-meta">
			{#if monograph.publisher_id}
				<EntityMetaItem label="Éditeur">
					<a href={resolve(`publishers/${monograph.publisher_id}`)}>{monograph.publisher_name}</a>
				</EntityMetaItem>
			{/if}
			{#if monograph.serial_id}
				<EntityMetaItem label="Collection">
					<a href={resolve(`journals/${monograph.serial_id}`)}>{monograph.journal_title}</a>
				</EntityMetaItem>
			{/if}
		</div>
	</div>

	<div class="m-publications">
		<PublicationsListView
			apiKey={`monograph-${monographId}-publications`}
			context={{ kind: 'monograph', id: monographId }}
			basePath={`/monographs/${monographId}`}
			perPage={50}
		/>
	</div>
{/if}

<style>
	.m-publications { margin-top: 28px; }
	.loading, .no-results { padding: 20px; color: var(--muted); }
</style>
