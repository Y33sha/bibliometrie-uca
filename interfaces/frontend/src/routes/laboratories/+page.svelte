<script lang="ts">
	import { onMount } from "svelte";
	import { base } from "$app/paths";
	import { api } from "$lib/api";

	import type { components } from "$lib/api/schema";
	type Lab = components["schemas"]["LaboratoryListItem"];

	let labs: Lab[] = $state([]);
	let search = $state("");
	let sortCol: "name" | "tutelles" = $state("name");
	let sortAsc = $state(true);

	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		let result = labs;
		if (q) {
			result = labs.filter(
				(l) =>
					l.name?.toLowerCase().includes(q) ||
					l.acronym?.toLowerCase().includes(q) ||
					l.code?.toLowerCase().includes(q),
			);
		}
		result = [...result].sort((a, b) => {
			let va: string, vb: string;
			if (sortCol === "name") {
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

	function toggleSort(col: "name" | "tutelles") {
		if (sortCol === col) {
			sortAsc = !sortAsc;
		} else {
			sortCol = col;
			sortAsc = true;
		}
	}

	function rorShortId(rorId: string): string {
		return rorId.replace("https://ror.org/", "");
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
		type="text"
		placeholder="Rechercher un laboratoire..."
		bind:value={search}
	/>
	<span class="count"
		>{filtered.length} laboratoire{filtered.length > 1 ? "s" : ""}</span
	>
</div>

<table>
	<thead>
		<tr>
			<th
				class:sorted={sortCol === "name"}
				onclick={() => toggleSort("name")}
			>
				Laboratoire
				<span class="sort-arrow"
					>{sortCol === "name" ? (sortAsc ? "▲" : "▼") : ""}</span
				>
			</th>
			<th
				class:sorted={sortCol === "tutelles"}
				onclick={() => toggleSort("tutelles")}
			>
				Co-tutelles
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
				<td>
					<a href="{base}/laboratories/{lab.id}" class="lab-link">
						<span class="lab-name">{lab.name}</span>
						{#if lab.acronym}
							<span class="lab-acronym">({lab.acronym})</span>
						{/if}
					</a>
				</td>
				<td>
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
							href={lab.ror_id}
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
	h2 {
		font-size: 1.2rem;
		font-weight: 600;
		margin: 0 0 14px;
	}
	.toolbar input[type="text"] {
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
		background: #f5f4f1;
		padding: 9px 12px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.3px;
		border-bottom: 1px solid var(--border);
		cursor: pointer;
		user-select: none;
		white-space: nowrap;
	}
	thead th:hover {
		color: var(--text);
	}
	tbody tr {
		border-bottom: 1px solid #f0efec;
	}
	tbody tr:last-child {
		border-bottom: none;
	}
	tbody tr:hover {
		background: #fafaf8;
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
		font-size: 0.85rem;
		color: var(--muted);
		margin-left: 6px;
	}
	.tutelles {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
</style>
