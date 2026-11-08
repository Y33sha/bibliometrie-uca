<script lang="ts">
	import { untrack } from 'svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { loadEntityFacet } from '#lib/entityFacets.js';
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import CheckboxOptions from '#lib/components/filters/CheckboxOptions.svelte';
	import EntityOptions from '#lib/components/filters/EntityOptions.svelte';
	import PresenceOptions from '#lib/components/filters/PresenceOptions.svelte';
	import RangeOptions from '#lib/components/filters/RangeOptions.svelte';
	import {
		clearValue,
		filterGroups,
		isActive,
		isAvailable,
		isShown,
		type CheckboxFilter,
		type EntityChoiceFilter,
		type FilterGroup,
		type FilterValues,
		type ListFilter,
		type PresenceCounts,
	} from '#lib/filterRegistry.js';
	import type { useFilterPanel } from '#lib/composables/useFilterPanel.svelte.js';

	// Panneau des filtres d'une liste : les filtres du registre, par rubrique, chacun dépliable. Un filet sépare les rubriques. Les décomptes suivent les filtres actifs.
	// Le contenu reste en place sous le pointeur : « Effacer » figure sur la ligne du nom du filtre, un filtre affiché reste affiché, et le panneau défile d'autant quand le contenu situé au-dessus du dernier filtre manipulé change de hauteur.
	let {
		filters,
		groups,
		values = $bindable(),
		options,
		presenceCounts,
		loaded,
		collapsed = false,
		entityEndpoint,
		buildParams,
		panel,
		onchange,
	}: {
		filters: ListFilter[];
		/** Rubriques du panneau, dans l'ordre d'affichage. */
		groups: readonly FilterGroup[];
		values: FilterValues;
		/** Options des cases à cocher, par clé de filtre. */
		options: Record<string, FacetOption[]>;
		/** Décomptes des éléments des filtres de présence, par clé d'élément. */
		presenceCounts: PresenceCounts;
		/** Décomptes chargés au moins une fois. Avant, tous les filtres proposés par la page s'affichent. */
		loaded: boolean;
		/** Filtres repliés à l'ouverture de la page, sauf les filtres actifs. Sans cette option, tous les filtres sont dépliés. */
		collapsed?: boolean;
		/** Base de la facette contextuelle des filtres d'entité. */
		entityEndpoint: string;
		/** Paramètres des filtres actifs, pour la facette contextuelle des entités. */
		buildParams: () => URLSearchParams;
		/** État du panneau : ouverture et filtres dépliés. */
		panel: ReturnType<typeof useFilterPanel>;
		/** Appelé après chaque changement de filtre. */
		onchange: () => void;
	} = $props();

	/** Options affichées d'un filtre à cases à cocher avant le bouton qui affiche les autres. */
	const OPTION_LIMIT = 5;

	// svelte-ignore state_referenced_locally
	const sections = filterGroups(filters, groups);
	// Une option sans décompte (liste fixe) compte comme disponible.
	const nonZeroOptions = (key: string): number => options[key]?.filter((o) => o.count !== 0).length ?? 0;

	/** Nombre affiché sur le nom d'un filtre actif : valeurs cochées, entités choisies, éléments filtrés et niveaux cochés ; un pour un intervalle. */
	function selectionCount(f: ListFilter): number {
		if (f.control === 'checkbox') return f.range ? 1 : (values.checkbox[f.key] ?? []).length;
		if (f.control === 'entity') return (values.entity[f.key] ?? []).length;
		return Object.keys(values.presence[f.key] ?? {}).length + (values.levels[f.key] ?? []).length;
	}

	function onCheckboxChange(filter: CheckboxFilter, selected: string[]) {
		values.checkbox[filter.key] = filter.normalize ? filter.normalize(selected) : selected;
		onchange();
	}

	function clear(filter: ListFilter) {
		clearValue(filter, values);
		onchange();
	}

	// Avant le premier chargement des décomptes, tous les filtres proposés s'affichent d'un coup : l'utilité d'un filtre se juge sur ses décomptes. Ensuite, un filtre affiché reste affiché, même sans option de décompte non nul.
	const everShown = new SvelteSet<string>();
	const visible = (f: ListFilter): boolean =>
		isAvailable(f) && (!loaded || everShown.has(f.key) || isShown(f, values, nonZeroOptions, presenceCounts));
	$effect(() => {
		if (!loaded) return;
		for (const f of filters) if (visible(f)) everShown.add(f.key);
	});

	/** Pause après un changement de filtre, avant le chargement d'avance des options des filtres d'entité : la liste et ses décomptes passent d'abord. */
	const PREFETCH_DELAY_MS = 800;

	// Options des filtres d'entité chargées d'avance, une requête à la fois, une fois les décomptes chargés : un filtre déplié lit ses options en cache.
	const prefetchKey = $derived(buildParams().toString());
	$effect(() => {
		void prefetchKey;
		if (!loaded) return;
		const kinds = untrack(() =>
			filters.filter((f): f is EntityChoiceFilter => f.control === 'entity' && visible(f)).map((f) => f.entity),
		);
		let cancelled = false;
		const timer = setTimeout(async () => {
			for (const kind of kinds) {
				if (cancelled) return;
				await loadEntityFacet(entityEndpoint, buildParams, kind).catch(() => {});
			}
		}, PREFETCH_DELAY_MS);
		return () => {
			cancelled = true;
			clearTimeout(timer);
		};
	});

	// Ancrage : le filtre manipulé en dernier et sa position à l'écran. Quand le panneau change de hauteur, il défile d'autant que le filtre s'est déplacé. L'ancrage expire après le rechargement des décomptes, ou dès que l'utilisateur fait défiler le panneau.
	const ANCHOR_MS = 3000;
	let aside: HTMLElement | undefined = $state();
	let anchor: { el: Element; top: number; until: number } | null = null;

	function setAnchor(e: Event) {
		const block = (e.target as Element).closest('.filter-block');
		anchor = block ? { el: block, top: block.getBoundingClientRect().top, until: performance.now() + ANCHOR_MS } : null;
	}

	$effect(() => {
		const scroller = aside?.parentElement;
		if (!aside || !scroller) return;
		const observer = new ResizeObserver(() => {
			if (!anchor || performance.now() > anchor.until || !anchor.el.isConnected) return;
			const delta = anchor.el.getBoundingClientRect().top - anchor.top;
			if (delta) scroller.scrollTop += delta;
		});
		observer.observe(aside);
		return () => observer.disconnect();
	});
</script>

<aside id="filter-panel" class="filter-panel" aria-label="Filtres" bind:this={aside} onpointerdowncapture={setAnchor} onkeydowncapture={setAnchor} onwheel={() => (anchor = null)} ontouchmove={() => (anchor = null)}>
	<div class="filter-panel-head">
		<span class="filter-panel-title">Filtres</span>
		<button type="button" class="btn-text filter-panel-close" onclick={() => (panel.open = false)}>Fermer</button>
	</div>
	{#each sections as s (s.group.key)}
		{@const shown = s.filters.filter(visible)}
		{#if shown.length}
			<section class="filter-group" aria-label={s.group.label}>
				{#each shown as f (f.key)}
					{@const active = isActive(f, values)}
					{@const open = panel.isExpanded(f.key, active || !collapsed)}
					<div class="filter-block">
						<div class="filter-head-row">
							<button type="button" class="filter-head" class:with-clear={active} aria-expanded={open} title={f.tooltip} onclick={() => panel.setExpanded(f.key, !open)}>
								<span class="filter-name">{f.label}</span>
								{#if active}<span class="facet-badge">{selectionCount(f)}</span>{/if}
								<span class="chevron" class:up={open} aria-hidden="true"></span>
							</button>
							{#if active}<button type="button" class="btn-text filter-clear" aria-label="Effacer le filtre {f.label}" onclick={() => clear(f)}>Effacer</button>{/if}
						</div>
						{#if open}
							<div class="filter-body">
								{#if f.control === 'checkbox' && f.range}
									<RangeOptions options={options[f.key] ?? []} bind:selected={values.checkbox[f.key]} onchange={(selected) => onCheckboxChange(f, selected)} />
								{:else if f.control === 'checkbox'}
									<CheckboxOptions options={options[f.key] ?? []} searchable={f.searchable} single={f.single} groups={f.groups} groupSeparators limit={OPTION_LIMIT} clearable={false} bind:selected={values.checkbox[f.key]} onchange={(selected) => onCheckboxChange(f, selected)} />
								{:else if f.control === 'entity'}
									<EntityOptions endpoint={entityEndpoint} kind={f.entity} multiple={f.multiple} limit={OPTION_LIMIT} clearable={false} {buildParams} selected={values.entity[f.key]} onchange={(ids) => { values.entity[f.key] = ids; onchange(); }} />
								{:else}
									<PresenceOptions items={f.items} bind:states={values.presence[f.key]} bind:checkedLevels={values.levels[f.key]} counts={presenceCounts} clearable={false} {onchange} />
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</section>
		{/if}
	{/each}
</aside>

<style>
	.filter-panel {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding-bottom: 16px;
	}
	/* En-tête du panneau, sur écran étroit seulement : sur grand écran, le bouton de la barre d'outils nomme et ferme le panneau. */
	.filter-panel-head {
		display: none;
		align-items: baseline;
		justify-content: space-between;
		padding: 4px 0 6px;
	}
	.filter-panel-title {
		font-weight: 600;
		font-size: var(--fs-md);
	}
	/* Rubriques séparées par un filet, sans titre. */
	.filter-group + .filter-group {
		margin-top: 4px;
		padding-top: 4px;
		border-top: 1px solid var(--border-subtle);
	}
	/* Nom du filtre, en bouton : fond teinté d'accent et texte assombri au survol. Le nom et les options gardent 6 px de marge intérieure, où le fond de survol déborde. */
	.filter-head {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		padding: 5px 6px;
		border: none;
		border-radius: var(--radius);
		background: none;
		font: inherit;
		font-size: var(--fs-md);
		font-weight: 600;
		color: var(--accent);
		text-align: left;
		cursor: pointer;
		transition: background-color 0.1s;
	}
	.filter-head:hover {
		background: var(--accent-light);
		color: color-mix(in srgb, var(--accent), black 20%);
	}
	.filter-head .chevron {
		margin-left: auto;
	}
	/* « Effacer » se pose sur la ligne du nom, devant le chevron, sans ajouter de ligne. */
	.filter-head-row {
		position: relative;
	}
	.filter-head.with-clear {
		padding-right: 76px;
	}
	.filter-head.with-clear .chevron {
		position: absolute;
		right: 6px;
	}
	.filter-clear {
		position: absolute;
		top: 50%;
		right: 26px;
		transform: translateY(-50%);
		font-size: var(--fs-sm);
	}
	.filter-body {
		margin: 0 0 6px;
		padding: 0 6px;
	}
	.filter-body :global(.option-row) {
		width: calc(100% + 12px);
		margin: 0 -6px;
		padding: 3px 6px;
		border-radius: var(--radius);
	}
	.filter-body :global(.panel-search) {
		width: 100%;
		margin: 2px 0 6px;
	}
	@media not all and (min-width: 1100px) {
		.filter-panel-head {
			display: flex;
		}
	}
</style>
