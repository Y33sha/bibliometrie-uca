<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	export interface TabDef {
		id: string;
		label: string;
		count?: number;
		showCount?: boolean;
	}

	interface Props {
		tabs: TabDef[];
		/** Called after the URL is updated. Use for lazy loading. */
		onswitch?: (tab: string) => void;
		/** Called after goto completes (e.g. to syncUrl). */
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
			{#if t.showCount !== false && t.count != null && t.count > 0}
				<span class="tab-count">{t.count}</span>
			{/if}
		</button>
	{/each}
</div>
