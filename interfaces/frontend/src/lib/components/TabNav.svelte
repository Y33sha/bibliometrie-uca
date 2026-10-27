<script lang="ts">
	import { page } from '$app/state';
	import { setQueryParam } from '#lib/url.js';
	import { scrollFade } from '#lib/actions/scrollFade.js';

	export interface TabDef {
		id: string;
		label: string;
		/** Nombre d'éléments de l'onglet, affiché à côté du libellé. */
		count?: number;
	}

	interface Props {
		tabs: TabDef[];
		/** Appelé après la mise à jour de l'URL. Sert au chargement paresseux. */
		onswitch?: (tab: string) => void;
		/** Appelé une fois la navigation terminée (ex. resynchroniser l'URL). */
		afterNavigate?: () => void;
	}

	let { tabs, onswitch, afterNavigate }: Props = $props();

	const defaultTab = $derived(tabs[0]?.id ?? '');

	const activeTab = $derived(
		(() => {
			const t = page.url.searchParams.get('tab');
			return t && tabs.some((tab) => tab.id === t) ? t : defaultTab;
		})()
	);

	function switchTab(tab: string) {
		if (tab === activeTab) return;
		const nav = setQueryParam('tab', tab === defaultTab ? null : tab);
		if (afterNavigate) nav.then(afterNavigate);
		onswitch?.(tab);
	}

	export function getActiveTab(): string {
		return activeTab;
	}
</script>

<div class="tabs" use:scrollFade>
	{#each tabs as t (t.id)}
		<button class="tab" class:active={activeTab === t.id} onclick={() => switchTab(t.id)}>
			{t.label}
			{#if t.count != null}<span class="tab-count">{t.count.toLocaleString('fr-FR')}</span>{/if}
		</button>
	{/each}
</div>
