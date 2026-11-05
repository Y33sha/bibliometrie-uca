<script lang="ts">
	import Breadcrumb from '#lib/components/Breadcrumb.svelte';
	import { pageTitle } from '#lib/institution.svelte.js';
	import type { PathnameWithSearchOrHash } from '$app/types';

	// Titre d'onglet et fil d'Ariane d'une page d'entité : la rubrique, puis le nom de l'entité une fois chargée.
	let {
		section,
		name,
		fallback,
		title,
	}: {
		/** Rubrique de l'entité, premier niveau du fil d'Ariane. */
		section: { label: string; path: PathnameWithSearchOrHash };
		/** Nom de l'entité ; absent tant qu'elle charge ou si elle est introuvable. */
		name?: string | null;
		/** Titre d'onglet en l'absence de nom, par exemple « Éditeur ». */
		fallback: string;
		/** Titre d'onglet distinct du nom affiché dans le fil d'Ariane. */
		title?: string | null;
	} = $props();
</script>

<svelte:head>
	<title>{pageTitle(title || name || fallback)}</title>
</svelte:head>

<Breadcrumb trail={[section]} current={name} />
