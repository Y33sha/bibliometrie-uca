<script lang="ts">
	import { formatNumber } from '#lib/utils.js';
	import { page } from '$app/state';
	import { replaceQuery } from '#lib/url.js';
	import { horizontalOverflow } from '#lib/actions/horizontalOverflow.js';
	import { activeTabId, type TabDef } from '#lib/tabs.js';

	// Onglets d'une page, inscrits dans l'URL (`?tab=`, omis pour le premier). Les autres paramètres de l'URL appartiennent à l'onglet affiché (filtres, tri, page d'une liste) : un changement d'onglet les efface, sauf ceux de `keep`.
	interface Props {
		tabs: TabDef[];
		/** Paramètres de l'URL propres à la page, gardés d'un onglet à l'autre : le volet de la fiche, par exemple. */
		keep?: string[];
	}

	let { tabs, keep = [] }: Props = $props();

	const defaultTab = $derived(tabs[0]?.id ?? '');

	const activeTab = $derived(activeTabId(tabs, page.url.searchParams));

	function switchTab(tab: string) {
		if (tab === activeTab) return;
		const current = new URLSearchParams(window.location.search);
		const params = new URLSearchParams();
		for (const key of keep) for (const value of current.getAll(key)) params.append(key, value);
		if (tab !== defaultTab) params.set('tab', tab);
		void replaceQuery(window.location.pathname, params);
	}
</script>

<div class="tabs" use:horizontalOverflow>
	{#each tabs as t (t.id)}
		<button class="tab" class:active={activeTab === t.id} onclick={() => switchTab(t.id)}>
			{t.label}
			{#if t.count != null}<span class="tab-count">{formatNumber(t.count)}</span>{/if}
		</button>
	{/each}
</div>
