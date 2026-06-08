<script lang="ts">
  import { base } from "$app/paths";
  import { titleCase } from "$lib/utils";
  import { structIsLabo, structLabel, type Authorship, type StructInfo } from "./types";

  const {
    authorships,
    structures,
  }: {
    authorships: Authorship[];
    structures: Record<string, StructInfo>;
  } = $props();

  function personName(last: string, first: string): string {
    return `${titleCase(first)} ${titleCase(last)}`;
  }
</script>

<div class="section">
  <h2 class="section-title">Auteurs ({authorships.length})</h2>
  <table class="auth-table">
    <thead>
      <tr>
        <th style="width:30px">#</th>
        <th>Auteur</th>
        <th>Structures</th>
        <th style="width:50px">Corr.</th>
        <th style="width:70px">Sources</th>
      </tr>
    </thead>
    <tbody>
      {#each authorships as a, i (i)}
        <tr class:uca-row={a.in_perimeter}>
          <td class="pos-cell">{(a.author_position ?? 0) + 1}</td>
          <td>
            <a href="{base}/persons/{a.person_id}" class="author-link">
              {personName(a.last_name, a.first_name)}
            </a>
          </td>
          <td>
            {#if a.structure_ids}
              {#each a.structure_ids as sid}
                {#if structIsLabo(structures, sid)}
                  <a href="{base}/laboratories/{sid}" class="struct-tag"
                    >{structLabel(structures, sid)}</a
                  >
                {:else}
                  <span class="struct-tag">{structLabel(structures, sid)}</span>
                {/if}
              {/each}
            {/if}
          </td>
          <td class="center-cell">
            {#if a.is_corresponding}
              <span title="Auteur correspondant">✉</span>
            {/if}
          </td>
          <td class="sources-cell">
            {#if a.source_hal}
              <span class="source-tag-label source-hal-label">H</span>
            {/if}
            {#if a.source_openalex}
              <span class="source-tag-label source-oa-label">OA</span>
            {/if}
            {#if a.source_wos}
              <span class="source-tag-label source-wos-label">W</span>
            {/if}
            {#if a.source_scanr}
              <span class="source-tag-label source-scanr-label">S</span>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>

<style>
  .section {
    margin-bottom: 16px;
  }
  .section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 8px;
  }
  .auth-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .auth-table :global(thead th) {
    background: #f5f4f1;
    padding: 8px 10px;
    text-align: left;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
    border-bottom: 2px solid var(--border);
    white-space: nowrap;
  }
  .auth-table tbody tr {
    border-bottom: 1px solid #f0efec;
  }
  .auth-table tbody tr:last-child {
    border-bottom: none;
  }
  .auth-table tbody tr:hover {
    background: #fafaf8;
  }
  .auth-table td {
    padding: 6px 10px;
    font-size: 0.95rem;
    vertical-align: middle;
  }
  .pos-cell {
    text-align: center;
    color: var(--muted);
    font-size: 0.85rem;
  }
  .center-cell {
    text-align: center;
  }
  .author-link {
    color: var(--accent);
    text-decoration: none;
  }
  .author-link:hover {
    text-decoration: underline;
  }
  .struct-tag {
    display: inline-block;
    padding: 1px 6px;
    background: var(--accent-light);
    border-radius: 3px;
    font-size: 0.8rem;
    color: var(--accent);
    font-weight: 500;
    margin-right: 3px;
    text-decoration: none;
  }
  a.struct-tag:hover {
    background: #d0e3f4;
    text-decoration: none;
  }
  .uca-row {
    background: #f8fcf9;
  }
  .sources-cell {
    white-space: nowrap;
  }
  .source-wos-label {
    background: #f0e8f5;
    color: #6b4c8a;
  }
</style>
