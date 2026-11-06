<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { latestRequest } from '#lib/api/index.js';
	import type { components } from '#lib/api/schema.js';
	import type { EntityKind } from '#lib/entityLabels.js';
	import { highlight } from '#lib/highlight.js';
	import { labListDefaults, type LabListDefaults } from '#lib/labListDefaults.js';
	import { formatCount } from '#lib/plural.js';

	type EntityFacetResponse = components['schemas']['EntityFacetResponse'];
	type PublicationListResponse = components['schemas']['PublicationListResponse'];
	type StructureListResponse = components['schemas']['StructureListResponse'];

	// Recherche transverse : labos, chercheurs, revues, éditeurs, sujets et publications. Pendant la frappe, chaque type est cherché à part, et ses premiers résultats s'affichent dès leur arrivée. Les flèches parcourent les résultats, Entrée ouvre le résultat choisi, Échap vide le champ.
	let { placeholder = 'Rechercher un labo, un chercheur, une revue, un sujet, une publication…' }: { placeholder?: string } = $props();

	/** Résultats affichés par type. */
	const PER_GROUP = 3;
	/** Nombre de caractères à partir duquel la recherche part. */
	const MIN_LENGTH = 2;
	/** Exclusion commune à la liste des publications. */
	const PUBLICATION_SCOPE = 'excluded_doc_type=ongoing_thesis';

	interface Result {
		href: string;
		label: string;
		/** Texte secondaire : nom complet, année, nombre de publications. */
		detail?: string;
		/** Lien vers tous les résultats du type, en fin de groupe. */
		more?: boolean;
	}

	interface Group {
		key: string;
		label: string;
		search: (term: string) => Promise<Result[]>;
	}

	let labDefaults: LabListDefaults | null = null;

	function entityGroup(key: string, label: string, kind: EntityKind, href: (id: string) => string): Group {
		const request = latestRequest();
		return {
			key,
			label,
			async search(term) {
				const params = new URLSearchParams({ kind, entity_search: term });
				const data = await request<EntityFacetResponse>(`/api/publications/facets/entities?${PUBLICATION_SCOPE}&${params}`);
				return data.entities.slice(0, PER_GROUP).map((e) => ({
					href: href(String(e.id)),
					label: e.label,
					detail: formatCount(e.count, 'publication'),
				}));
			},
		};
	}

	const labRequest = latestRequest();
	const publicationRequest = latestRequest();

	const GROUPS: Group[] = [
		{
			key: 'labs',
			label: 'Labos',
			async search(term) {
				labDefaults ??= await labListDefaults();
				const params = new URLSearchParams({ search: term, per_page: String(PER_GROUP) });
				if (labDefaults.types.length) params.set('structure_type', labDefaults.types.join(','));
				if (labDefaults.perimeters.length) params.set('perimeter_id', labDefaults.perimeters.join(','));
				const data = await labRequest<StructureListResponse>(`/api/structures?${params}`);
				return data.structures.map((s) => ({
					href: resolve(`structures/${s.id}`),
					label: s.acronym || s.name,
					detail: s.acronym ? s.name : undefined,
				}));
			},
		},
		entityGroup('persons', 'Chercheurs', 'person', (id) => resolve(`persons/${id}`)),
		entityGroup('serials', 'Revues', 'serial', (id) => resolve(`journals/${id}`)),
		entityGroup('publishers', 'Éditeurs', 'publisher', (id) => resolve(`publishers/${id}`)),
		entityGroup('subjects', 'Sujets', 'subject', (id) => resolve(`subjects/${encodeURIComponent(id)}`)),
		{
			key: 'publications',
			label: 'Publications',
			async search(term) {
				const params = new URLSearchParams({ search: term, per_page: String(PER_GROUP) });
				const data = await publicationRequest<PublicationListResponse>(`/api/publications?${PUBLICATION_SCOPE}&${params}`);
				const results: Result[] = data.publications.map((p) => ({
					href: resolve(`publications/${p.id}`),
					label: p.title,
					detail: p.publication_year ? String(p.publication_year) : undefined,
				}));
				if (data.total > results.length) {
					results.push({
						href: `${resolve('publications')}?${new URLSearchParams({ search: term })}`,
						label: `Voir les ${formatCount(data.total, 'publication')}`,
						more: true,
					});
				}
				return results;
			},
		},
	];

	let query = $state('');
	let open = $state(false);
	let results = $state<Record<string, Result[]>>({});
	let active = $state(-1);
	let debounce: ReturnType<typeof setTimeout>;
	let root: HTMLElement | undefined = $state();

	const term = $derived(query.trim());
	const shownGroups = $derived(GROUPS.filter((g) => results[g.key]?.length));
	// Résultats dans l'ordre d'affichage, pour la navigation au clavier.
	const flat = $derived(shownGroups.flatMap((g) => results[g.key]));
	const expanded = $derived(open && term.length >= MIN_LENGTH && shownGroups.length > 0);

	function search() {
		results = {};
		active = -1;
		if (term.length < MIN_LENGTH) return;
		const current = term;
		for (const g of GROUPS) {
			g.search(current)
				.then((items) => {
					if (current === term) results = { ...results, [g.key]: items };
				})
				.catch(() => {});
		}
	}

	function onInput() {
		open = true;
		clearTimeout(debounce);
		debounce = setTimeout(search, 250);
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			query = '';
			results = {};
			open = false;
			return;
		}
		if (!expanded) return;
		if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
			e.preventDefault();
			const step = e.key === 'ArrowDown' ? 1 : -1;
			active = (active + step + flat.length) % flat.length;
		} else if (e.key === 'Enter' && active >= 0) {
			e.preventDefault();
			goto(flat[active].href);
		}
	}

	function onFocusOut(e: FocusEvent) {
		if (!root?.contains(e.relatedTarget as Node)) open = false;
	}

	function optionIndex(result: Result): number {
		return flat.indexOf(result);
	}
</script>

{#snippet marked(text: string)}{#each highlight(text, term) as s, j (j)}{#if s.match}<mark>{s.text}</mark>{:else}{s.text}{/if}{/each}{/snippet}

<div class="global-search" bind:this={root} onfocusout={onFocusOut}>
	<input
		type="search"
		class="global-search-input"
		role="combobox"
		aria-label="Rechercher"
		aria-expanded={expanded}
		aria-controls="global-search-results"
		aria-autocomplete="list"
		aria-activedescendant={active >= 0 ? `global-search-option-${active}` : undefined}
		{placeholder}
		bind:value={query}
		oninput={onInput}
		onkeydown={onKeydown}
		onfocus={() => (open = true)}
	/>
	{#if expanded}
		<div id="global-search-results" class="global-search-results popover" role="listbox" aria-label="Résultats">
			{#each shownGroups as g (g.key)}
				<div class="result-group" role="group" aria-labelledby="global-search-group-{g.key}">
					<div id="global-search-group-{g.key}" class="result-group-label">{g.label}</div>
					{#each results[g.key] as r (r.href)}
						{@const i = optionIndex(r)}
						<a
							id="global-search-option-{i}"
							class="result"
							class:active={i === active}
							class:more={r.more}
							role="option"
							aria-selected={i === active}
							href={r.href}
							onpointerenter={() => (active = i)}
						>
							<span class="result-label">{#if r.more}{r.label}{:else}{@render marked(r.label)}{/if}</span>
							{#if r.detail}<span class="result-detail">{@render marked(r.detail)}</span>{/if}
						</a>
					{/each}
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.global-search {
		position: relative;
	}
	.global-search-input {
		width: 100%;
		height: 52px;
		padding: 0 18px 0 46px;
		border-radius: var(--radius);
		font-size: var(--fs-lg);
		background: var(--card)
			url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='7'/%3E%3Cpath d='M20 20l-3.5-3.5'/%3E%3C/svg%3E")
			no-repeat 16px center;
	}
	.global-search-results {
		position: absolute;
		z-index: 50;
		top: calc(100% + 4px);
		left: 0;
		right: 0;
		max-height: min(70vh, 560px);
		overflow-y: auto;
		padding: 6px 0;
	}
	.result-group + .result-group {
		margin-top: 4px;
		padding-top: 4px;
		border-top: 1px solid var(--border-subtle);
	}
	.result-group-label {
		padding: 4px 16px 2px;
		font-size: var(--fs-sm);
		font-weight: 600;
		color: var(--muted);
	}
	.result {
		display: flex;
		align-items: baseline;
		gap: 12px;
		padding: 5px 16px;
		color: var(--text);
		text-decoration: none;
	}
	.result.active {
		background: var(--accent-light);
	}
	.result-label {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.result-detail {
		flex: 1 1 auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--fs-sm);
		color: var(--muted);
	}
	.result.more .result-label {
		color: var(--accent);
		font-size: var(--fs-sm);
		font-weight: 600;
	}
	mark {
		background: color-mix(in srgb, var(--warning) 35%, transparent);
		color: inherit;
		border-radius: 2px;
	}
</style>
