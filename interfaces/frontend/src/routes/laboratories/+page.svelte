<script lang="ts">
	import { onMount } from "svelte";
	import { autofocus } from "$lib/actions/focus";
	import { base } from "$app/paths";
	import { api } from "$lib/api";
	import { rorShortId, rorFullUrl } from "$lib/utils";
	import FacetDropdown from "$lib/components/FacetDropdown.svelte";

	import type { components } from "$lib/api/schema";
	type Lab = components["schemas"]["LaboratoryListItem"];

	let labs: Lab[] = $state([]);
	let search = $state("");
	let selectedTutelles = $state<string[]>([]);
	let sortCol: "acronym" | "name" | "tutelles" = $state("acronym");
	let sortAsc = $state(true);

	// Options de la facette « tutelles » : tutelles distinctes de tous les labos, avec le nombre de
	// labos rattachés, triées par fréquence décroissante.
	const tutelleOptions = $derived.by(() => {
		const byId = new Map<string, { text: string; count: number }>();
		for (const lab of labs) {
			for (const t of lab.tutelles || []) {
				const key = String(t.id);
				const entry = byId.get(key) ?? { text: t.acronym || t.name || key, count: 0 };
				entry.count++;
				byId.set(key, entry);
			}
		}
		return [...byId.entries()]
			.map(([value, { text, count }]) => ({ value, text, count }))
			.sort((a, b) => b.count - a.count || a.text.localeCompare(b.text));
	});

	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		let result = labs;
		if (q) {
			result = result.filter(
				(l) =>
					l.name?.toLowerCase().includes(q) ||
					l.acronym?.toLowerCase().includes(q) ||
					l.code?.toLowerCase().includes(q),
			);
		}
		if (selectedTutelles.length) {
			result = result.filter((l) =>
				(l.tutelles || []).some((t) => selectedTutelles.includes(String(t.id))),
			);
		}
		result = [...result].sort((a, b) => {
			let va: string, vb: string;
			if (sortCol === "acronym") {
				va = (a.acronym || "").toLowerCase();
				vb = (b.acronym || "").toLowerCase();
			} else if (sortCol === "name") {
				va = (a.name || "").toLowerCase();
				vb = (b.name || "").toLowerCase();
			} else {
				va = (a.tutelles || [])
					.map((t) => t.acronym || t.name)
					.join(", ")
					.toLowerCase();
				vb = (b.tutelles || [])
					.map((t) => t.acronym || t.name)
					.join(", ")
					.toLowerCase();
			}
			if (va < vb) return sortAsc ? -1 : 1;
			if (va > vb) return sortAsc ? 1 : -1;
			return 0;
		});
		return result;
	});

	function toggleSort(col: "acronym" | "name" | "tutelles") {
		if (sortCol === col) {
			sortAsc = !sortAsc;
		} else {
			sortCol = col;
			sortAsc = true;
		}
	}

	onMount(async () => {
		labs = await api<Lab[]>("/api/laboratories");
	});
</script>

<svelte:head>
	<title>Laboratoires — Bibliométrie UCA</title>
</svelte:head>

<div class="toolbar toolbar-card">
	<input
		type="search"
		placeholder="Rechercher un laboratoire..."
		bind:value={search}
		use:autofocus
		onkeydown={(e) => { if (e.key === 'Escape') { search = ''; } }}
	/>
	<FacetDropdown label="Tutelles" options={tutelleOptions} searchable bind:selected={selectedTutelles} />
	<span class="count"
		>{filtered.length} laboratoire{filtered.length > 1 ? "s" : ""}</span
	>
</div>

<table>
	<thead>
		<tr>
			<th
				class:sorted={sortCol === "acronym"}
				onclick={() => toggleSort("acronym")}
			>
				Acronyme
				<span class="sort-arrow"
					>{sortCol === "acronym" ? (sortAsc ? "▲" : "▼") : ""}</span
				>
			</th>
			<th
				class:sorted={sortCol === "name"}
				onclick={() => toggleSort("name")}
			>
				Nom
				<span class="sort-arrow"
					>{sortCol === "name" ? (sortAsc ? "▲" : "▼") : ""}</span
				>
			</th>
			<th
				class="tutelles-col"
				class:sorted={sortCol === "tutelles"}
				onclick={() => toggleSort("tutelles")}
			>
				Tutelles
				<span class="sort-arrow"
					>{sortCol === "tutelles"
						? sortAsc
							? "▲"
							: "▼"
						: ""}</span
				>
			</th>
			<th>ROR</th>
			<th>Collection HAL</th>
		</tr>
	</thead>
	<tbody>
		{#each filtered as lab (lab.id)}
			<tr>
				<td class="acronym-cell">
					<a href="{base}/laboratories/{lab.id}" class="lab-link">
						<span class="lab-acronym">{lab.acronym}</span>
					</a>
				</td>
				<td>
					<a href="{base}/laboratories/{lab.id}" class="lab-link">
						<span class="lab-name">{lab.name}</span>
					</a>
				</td>
				<td class="tutelles-col">
					<div class="tutelles">
						{#each lab.tutelles || [] as t (t.id)}
							<span class="tutelle-tag"
								>{t.acronym || t.name}</span
							>
						{/each}
					</div>
				</td>
				<td>
					{#if lab.ror_id}
						<a
							href={rorFullUrl(lab.ror_id)}
							target="_blank"
							rel="noopener"
							class="id-badge"
						>
							{rorShortId(lab.ror_id)}
						</a>
					{/if}
				</td>
				<td>
					{#if lab.hal_collection}
						<a
							href="https://hal.science/{lab.hal_collection}"
							target="_blank"
							rel="noopener"
							class="id-badge"
						>
							{lab.hal_collection}
						</a>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<style>
	.toolbar input[type="search"] {
		width: 260px;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	thead th {
		background: var(--surface);
		padding: 9px 12px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 1px solid var(--border);
		cursor: pointer;
		user-select: none;
		white-space: nowrap;
	}
	thead th:hover {
		color: var(--text);
	}
	tbody tr {
		border-bottom: 1px solid var(--border-subtle);
	}
	tbody tr:last-child {
		border-bottom: none;
	}
	tbody tr:hover {
		background: var(--surface-hover);
	}
	td {
		padding: 10px 12px;
		font-size: 0.95rem;
		vertical-align: middle;
	}
	td a {
		color: var(--accent);
		text-decoration: none;
	}
	td a:not(.id-badge, .lab-tag, .source-tag):hover {
		text-decoration: underline;
	}
	.lab-link {
		text-decoration: none;
		color: inherit;
	}
	.lab-link:hover .lab-name {
		color: var(--accent);
		text-decoration: underline;
	}
	.lab-name {
		font-weight: 500;
	}
	.lab-acronym {
		font-weight: 600;
		white-space: nowrap;
	}
	.tutelles-col {
		width: 1%;
		white-space: nowrap;
	}
	.tutelles {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
</style>
