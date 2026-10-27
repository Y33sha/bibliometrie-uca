<script lang="ts">
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { columnLabels, filterLabels } from '#lib/labels.js';
	import { pageTitle } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { api, ApiError, structures as structuresApi } from '#lib/api/index.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { rorShortId, rorFullUrl } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import { STRUCTURE_TYPES } from '#lib/structureTypes.js';
	import FacetDropdown, { type FacetOption } from '#lib/components/FacetDropdown.svelte';
	import StructureFormModal from './StructureFormModal.svelte';
	import { API_SOURCES, ROR_FORMAT_ERROR, buildApiIds, normalizeRorId } from './types';

	import type { components } from '#lib/api/schema.js';
	type Structure = components['schemas']['StructureListItem'];
	type Perimeter = components['schemas']['PerimeterOut'];
	type ConfigItem = components['schemas']['ConfigItem'];

	// Toutes les structures, filtrées dans la page : elles se comptent en dizaines.
	let structures: Structure[] = $state([]);
	let perimeters: Perimeter[] = $state([]);
	let search = $state('');
	let selectedTypes = $state<string[]>([]);
	let selectedTutelles = $state<string[]>([]);
	// Identifiants de périmètre en chaîne, ou `none` pour les structures hors de tout périmètre. Par défaut, le périmètre des personnes ; seule la session admin change ce réglage.
	let selectedPerimeters = $state<string[]>([]);
	let sortCol: 'acronym' | 'name' | 'tutelles' = $state('acronym');
	let sortAsc = $state(true);

	type Filter = 'search' | 'types' | 'tutelles' | 'perimeters';

	function matches(s: Structure, skip?: Filter): boolean {
		const q = search.trim().toLowerCase();
		if (skip !== 'search' && q && !(
			s.name?.toLowerCase().includes(q) ||
			s.acronym?.toLowerCase().includes(q) ||
			s.code?.toLowerCase().includes(q)
		)) return false;
		if (skip !== 'types' && selectedTypes.length && !selectedTypes.includes(s.type)) return false;
		if (skip !== 'tutelles' && selectedTutelles.length &&
			!(s.tutelles || []).some((t) => selectedTutelles.includes(String(t.id)))) return false;
		if (skip !== 'perimeters' && selectedPerimeters.length && !selectedPerimeters.some((p) =>
			p === 'none' ? s.perimeter_ids.length === 0 : s.perimeter_ids.includes(Number(p))
		)) return false;
		return true;
	}

	// Chaque facette compte les structures retenues par les autres filtres.
	const typeOptions = $derived.by((): FacetOption[] => {
		const counts = new Map<string, number>();
		for (const s of structures) if (matches(s, 'types')) counts.set(s.type, (counts.get(s.type) ?? 0) + 1);
		return STRUCTURE_TYPES.filter((t) => counts.has(t.value) || selectedTypes.includes(t.value))
			.map((t) => ({ value: t.value, text: t.label, count: counts.get(t.value) ?? 0 }));
	});

	// Tutelles distinctes des structures retenues, avec le nombre de structures rattachées, par fréquence décroissante.
	const tutelleOptions = $derived.by((): FacetOption[] => {
		const byId = new Map<string, { text: string; count: number }>();
		for (const s of structures) {
			if (!matches(s, 'tutelles')) continue;
			for (const t of s.tutelles || []) {
				const key = String(t.id);
				const entry = byId.get(key) ?? { text: structureLabel(t) || key, count: 0 };
				entry.count++;
				byId.set(key, entry);
			}
		}
		return [...byId.entries()]
			.map(([value, { text, count }]) => ({ value, text, count }))
			.sort((a, b) => b.count - a.count || a.text.localeCompare(b.text));
	});

	const perimeterOptions = $derived.by((): FacetOption[] => {
		const candidates = structures.filter((s) => matches(s, 'perimeters'));
		return [
			...perimeters.map((p) => ({
				value: String(p.id),
				text: p.name,
				count: candidates.filter((s) => s.perimeter_ids.includes(p.id)).length,
			})),
			{ value: 'none', text: 'Hors périmètre', count: candidates.filter((s) => s.perimeter_ids.length === 0).length },
		];
	});

	const filtered = $derived.by(() => {
		const sortKey = (s: Structure): string => {
			if (sortCol === 'acronym') return (s.acronym || s.name || '').toLowerCase();
			if (sortCol === 'name') return (s.name || '').toLowerCase();
			return (s.tutelles || []).map(structureLabel).join(', ').toLowerCase();
		};
		return structures
			.filter((s) => matches(s))
			.sort((a, b) => {
				const va = sortKey(a);
				const vb = sortKey(b);
				if (va < vb) return sortAsc ? -1 : 1;
				if (va > vb) return sortAsc ? 1 : -1;
				return 0;
			});
	});

	// Le type s'affiche dès que la liste mêle plusieurs types.
	const showTypeColumn = $derived(selectedTypes.length !== 1);

	function toggleSort(col: 'acronym' | 'name' | 'tutelles') {
		if (sortCol === col) {
			sortAsc = !sortAsc;
		} else {
			sortCol = col;
			sortAsc = true;
		}
	}

	// Création d'une structure (session admin)
	let createModalOpen = $state(false);
	let mCode = $state('');
	let mName = $state('');
	let mAcronym = $state('');
	let mType = $state('labo');
	let mRor = $state('');
	let mHal = $state('');
	let mApiIds: Record<string, string> = $state({});

	function openCreateModal() {
		mCode = '';
		mName = '';
		mAcronym = '';
		mType = 'labo';
		mRor = '';
		mHal = '';
		mApiIds = {};
		for (const src of API_SOURCES) mApiIds[src] = '';
		createModalOpen = true;
	}

	async function submitCreate() {
		const ror = normalizeRorId(mRor);
		if (ror === null) {
			toast(ROR_FORMAT_ERROR, 'error');
			return;
		}
		mRor = ror;
		const data: Record<string, any> = {
			code: mCode.trim(),
			name: mName.trim(),
			acronym: mAcronym.trim() || null,
			type: mType,
			ror_id: mRor.trim() || null,
			hal_collection: mHal.trim() || null,
			api_ids: buildApiIds(mApiIds),
		};
		if (!data.code || !data.name) {
			toast('Code et nom requis', 'error');
			return;
		}
		try {
			const created = (await structuresApi.create(data)) as { id: number };
			createModalOpen = false;
			goto(resolve(`structures/${created.id}?tab=management`));
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur: ' + msg, 'error');
		}
	}

	onMount(async () => {
		const [config, all, perimeterList] = await Promise.all([
			api<ConfigItem[]>('/api/config'),
			api<Structure[]>('/api/structures'),
			api<Perimeter[]>('/api/perimeters'),
		]);
		// Les types affichés par défaut suivent la configuration.
		selectedTypes = (config.find((c) => c.key === 'laboratories_display_types')?.value ?? ['labo']) as string[];
		const persons = perimeterList.find((p) => p.is_persons);
		selectedPerimeters = persons ? [String(persons.id)] : [];
		perimeters = perimeterList;
		structures = all;
	});
</script>

<svelte:head>
	<title>{pageTitle('Labos')}</title>
</svelte:head>

<h1 class="visually-hidden">Labos</h1>

<div class="toolbar toolbar-card">
	<input
		type="search"
		placeholder="Rechercher par nom ou acronyme"
		bind:value={search}
		onkeydown={(e) => { if (e.key === 'Escape') { search = ''; } }}
	/>
	<FacetDropdown label={filterLabels.types} options={typeOptions} bind:selected={selectedTypes} />
	<FacetDropdown label="Tutelles" options={tutelleOptions} searchable bind:selected={selectedTutelles} />
	{#if isAdmin()}
		<FacetDropdown label="Périmètre" options={perimeterOptions} bind:selected={selectedPerimeters} />
	{/if}
	<span class="count">{filtered.length} structure{filtered.length > 1 ? 's' : ''}</span>
	{#if isAdmin()}
		<button class="btn btn-primary btn-sm" onclick={openCreateModal}>+ Nouvelle</button>
	{/if}
</div>

<table class="data-table">
	<thead>
		<tr>
			{#if showTypeColumn}<th>{columnLabels.type}</th>{/if}
			<th class="sortable" class:active={sortCol === 'acronym'} onclick={() => toggleSort('acronym')}>
				Acronyme
				<SortChevron direction={sortCol === 'acronym' ? (sortAsc ? 'asc' : 'desc') : null} />
			</th>
			<th class="sortable" class:active={sortCol === 'name'} onclick={() => toggleSort('name')}>
				Nom
				<SortChevron direction={sortCol === 'name' ? (sortAsc ? 'asc' : 'desc') : null} />
			</th>
			<th class="sortable tutelles-col" class:active={sortCol === 'tutelles'} onclick={() => toggleSort('tutelles')}>
				Tutelles
				<SortChevron direction={sortCol === 'tutelles' ? (sortAsc ? 'asc' : 'desc') : null} />
			</th>
			<th>ROR</th>
			<th>Collection HAL</th>
		</tr>
	</thead>
	<tbody>
		{#each filtered as s (s.id)}
			<tr>
				{#if showTypeColumn}
					<td><span class="structure-type structure-type-{s.type}">{s.type}</span></td>
				{/if}
				<td class="acronym-cell">
					{#if s.acronym}<a href={resolve(`structures/${s.id}`)} class="entity-link">{s.acronym}</a>{/if}
				</td>
				<td>
					<a href={resolve(`structures/${s.id}`)} class="entity-link">{s.name}</a>
				</td>
				<td class="tutelles-col">
					<div class="tutelles">
						{#each s.tutelles || [] as t (t.id)}
							<span class="tutelle-tag">{structureLabel(t)}</span>
						{/each}
					</div>
				</td>
				<td>
					{#if s.ror_id}
						<a href={rorFullUrl(s.ror_id)} target="_blank" rel="noopener" class="id-badge">
							{rorShortId(s.ror_id)}
						</a>
					{/if}
				</td>
				<td>
					{#if s.hal_collection}
						<a href="https://hal.science/{s.hal_collection}" target="_blank" rel="noopener" class="id-badge">
							{s.hal_collection}
						</a>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

{#if createModalOpen}
	<StructureFormModal
		editMode={false}
		bind:code={mCode}
		bind:name={mName}
		bind:acronym={mAcronym}
		bind:type={mType}
		bind:ror={mRor}
		bind:hal={mHal}
		bind:apiIds={mApiIds}
		onclose={() => (createModalOpen = false)}
		onsubmit={submitCreate}
	/>
{/if}

<style>
	.toolbar input[type='search'] {
		width: 260px;
	}
	td {
		vertical-align: middle;
	}
	.acronym-cell {
		white-space: nowrap;
	}
	.acronym-cell .entity-link {
		font-weight: 600;
	}
	.tutelles-col {
		width: 1%;
		min-width: 150px;
		white-space: nowrap;
	}
	.tutelles {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
</style>
