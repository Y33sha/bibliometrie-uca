<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	export interface TabDef {
		id: string;
		label: string;
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
			const t = $page.url.searchParams.get('tab');
			return t && tabs.some((tab) => tab.id === t) ? t : defaultTab;
		})()
	);

	function switchTab(tab: string) {
		if (tab === activeTab) return;
		const url = new URL($page.url);
		if (tab === defaultTab) {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		const nav = goto(url.toString(), { replaceState: true, noScroll: true });
		if (afterNavigate) nav.then(afterNavigate);
		onswitch?.(tab);
	}

	export function getActiveTab(): string {
		return activeTab;
	}
</script>

<div class="tabs">
	{#each tabs as t (t.id)}
		<button class="tab" class:active={activeTab === t.id} onclick={() => switchTab(t.id)}>
			{t.label}
		</button>
	{/each}
</div>
