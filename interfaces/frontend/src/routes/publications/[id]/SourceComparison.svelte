<script lang="ts">
  import { base } from "$app/paths";
  import { publications } from "$lib/api";
  import Tooltip from "$lib/components/Tooltip.svelte";
  import {
    structIsLabo,
    structLabel,
    structsTooltip,
    type PubResponse,
    type Source,
    type SourceAuthorship,
    type SourceRow,
    type StructInfo,
  } from "./types";

  const {
    data,
    sourceRows,
    hasSourceConflict,
    halSource,
    oaSource,
    wosSource,
    structures,
    isAdmin,
    onChange,
  }: {
    data: PubResponse;
    sourceRows: SourceRow[];
    hasSourceConflict: boolean;
    halSource: Source | undefined;
    oaSource: Source | undefined;
    wosSource: Source | undefined;
    structures: Record<string, StructInfo>;
    isAdmin: boolean;
    onChange: () => void | Promise<void>;
  } = $props();

  async function toggleExclude(source: string, a: SourceAuthorship) {
    const newExcluded = !a.excluded;
    await publications.excludeSourceAuthorship(source, a.id, { excluded: newExcluded });
    await onChange();
  }

  const sourceCount = $derived(
    (data.hal_authorships.length ? 1 : 0) +
      (data.openalex_authorships.length ? 1 : 0) +
      (data.wos_authorships.length ? 1 : 0),
  );

  const singleSource = $derived<"hal" | "openalex" | "wos">(
    halSource ? "hal" : oaSource ? "openalex" : "wos",
  );
  const singleRows = $derived<SourceAuthorship[]>(
    halSource
      ? data.hal_authorships
      : oaSource
        ? data.openalex_authorships
        : data.wos_authorships,
  );
  const singleLabel = $derived(halSource ? "HAL" : oaSource ? "OpenAlex" : "WoS");
  const singleSourceData = $derived(halSource || oaSource || wosSource);
</script>

{#if sourceCount > 1}
  <details class="source-details">
    <summary
      class:source-conflict={hasSourceConflict}
      class:source-ok={!hasSourceConflict}
    >
      {#if hasSourceConflict}
        <span class="status-icon conflict-icon">!</span> Conflit entre sources
      {:else}
        <span class="status-icon ok-icon">&#10003;</span> Sources cohérentes
      {/if}
      <span class="source-summary-count">
        ({sourceRows.length} auteurs &mdash;
        {#if halSource}H{/if}{#if oaSource}{halSource ? "/" : ""}OA{/if}{#if wosSource}{halSource || oaSource ? "/" : ""}W{/if})
      </span>
    </summary>
    <div class="source-grid-wrap">
      <table class="source-grid">
        <thead>
          <tr>
            {#if halSource}
              <th class="sg-pos">#</th>
              <th class="sg-name">HAL</th>
            {/if}
            {#if oaSource}
              <th class="sg-pos">#</th>
              <th class="sg-name">OpenAlex</th>
            {/if}
            {#if wosSource}
              <th class="sg-pos">#</th>
              <th class="sg-name">WoS</th>
            {/if}
          </tr>
        </thead>
        <tbody>
          <tr class="countries-row">
            {#if halSource}
              <td class="sg-pos-cell"></td>
              <td class="sg-name-cell countries-cell"
                >{(halSource.countries || []).map((c) => c.toUpperCase()).join(" ")}</td
              >
            {/if}
            {#if oaSource}
              <td class="sg-pos-cell"></td>
              <td class="sg-name-cell countries-cell"
                >{(oaSource.countries || []).map((c) => c.toUpperCase()).join(" ")}</td
              >
            {/if}
            {#if wosSource}
              <td class="sg-pos-cell"></td>
              <td class="sg-name-cell countries-cell"
                >{(wosSource.countries || []).map((c) => c.toUpperCase()).join(" ")}</td
              >
            {/if}
          </tr>
          {#each sourceRows as row (row.position)}
            <tr class:conflict-row={row.conflict}>
              {#if halSource}
                <td class="sg-pos-cell">{#if row.hal}{row.position + 1}{/if}</td>
                <td class="sg-name-cell" class:sg-excluded={row.hal?.excluded}>
                  {#if row.hal}
                    {#if isAdmin}<button
                        class="exclude-btn"
                        title={row.hal.excluded ? "Rétablir" : "Marquer comme faux"}
                        onclick={() => toggleExclude("hal", row.hal!)}
                        >{row.hal.excluded ? "↩" : "×"}</button
                      >{/if}
                    {#if row.hal.person_id}
                      <a
                        href="{base}/persons/{row.hal.person_id}"
                        class="sg-author-link"
                        class:sg-uca={row.hal.in_perimeter}
                      >
                        {row.hal.full_name}
                      </a>
                    {:else}
                      <span class="sg-author" class:sg-uca={row.hal.in_perimeter}>
                        {row.hal.full_name}
                      </span>
                    {/if}
                    {#if structsTooltip(row.hal, structures)}
                      <Tooltip text={structsTooltip(row.hal, structures)}
                        ><span class="info-icon">&#9432;</span></Tooltip
                      >
                    {/if}
                    {#if row.hal.countries}
                      <span class="author-countries"
                        >{row.hal.countries.map((c) => c.toUpperCase()).join(" ")}</span
                      >
                    {/if}
                  {/if}
                </td>
              {/if}
              {#if oaSource}
                <td class="sg-pos-cell">{#if row.oa}{row.position + 1}{/if}</td>
                <td class="sg-name-cell" class:sg-excluded={row.oa?.excluded}>
                  {#if row.oa}
                    {#if isAdmin}<button
                        class="exclude-btn"
                        title={row.oa.excluded ? "Rétablir" : "Marquer comme faux"}
                        onclick={() => toggleExclude("openalex", row.oa!)}
                        >{row.oa.excluded ? "↩" : "×"}</button
                      >{/if}
                    {#if row.oa.person_id}
                      <a
                        href="{base}/persons/{row.oa.person_id}"
                        class="sg-author-link"
                        class:sg-uca={row.oa.in_perimeter}
                      >
                        {row.oa.full_name}
                      </a>
                    {:else}
                      <span class="sg-author" class:sg-uca={row.oa.in_perimeter}>
                        {row.oa.full_name}
                      </span>
                    {/if}
                    {#if structsTooltip(row.oa, structures)}
                      <Tooltip text={structsTooltip(row.oa, structures)}
                        ><span class="info-icon">&#9432;</span></Tooltip
                      >
                    {/if}
                    {#if row.oa.countries}
                      <span class="author-countries"
                        >{row.oa.countries.map((c) => c.toUpperCase()).join(" ")}</span
                      >
                    {/if}
                  {/if}
                </td>
              {/if}
              {#if wosSource}
                <td class="sg-pos-cell">{#if row.wos}{row.position + 1}{/if}</td>
                <td class="sg-name-cell" class:sg-excluded={row.wos?.excluded}>
                  {#if row.wos}
                    {#if isAdmin}<button
                        class="exclude-btn"
                        title={row.wos.excluded ? "Rétablir" : "Marquer comme faux"}
                        onclick={() => toggleExclude("wos", row.wos!)}
                        >{row.wos.excluded ? "↩" : "×"}</button
                      >{/if}
                    {#if row.wos.person_id}
                      <a
                        href="{base}/persons/{row.wos.person_id}"
                        class="sg-author-link"
                        class:sg-uca={row.wos.in_perimeter}
                      >
                        {row.wos.full_name}
                      </a>
                    {:else}
                      <span class="sg-author" class:sg-uca={row.wos.in_perimeter}>
                        {row.wos.full_name}
                      </span>
                    {/if}
                    {#if structsTooltip(row.wos, structures)}
                      <Tooltip text={structsTooltip(row.wos, structures)}
                        ><span class="info-icon">&#9432;</span></Tooltip
                      >
                    {/if}
                    {#if row.wos.countries}
                      <span class="author-countries"
                        >{row.wos.countries.map((c) => c.toUpperCase()).join(" ")}</span
                      >
                    {/if}
                  {/if}
                </td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </details>
{:else if sourceCount === 1}
  <div class="section">
    <h2 class="section-title">
      Auteurs — source {singleLabel} ({singleRows.filter((a) => !a.excluded).length})
    </h2>
    {#if singleSourceData?.countries?.length}
      <div class="countries-cell" style="margin-bottom: 8px;">
        Pays : {singleSourceData.countries.map((c) => c.toUpperCase()).join(" ")}
      </div>
    {/if}
    <table class="auth-table">
      <thead>
        <tr>
          <th style="width:30px">#</th>
          <th>Auteur</th>
          <th>Affiliations</th>
          <th style="width:50px">Pays</th>
        </tr>
      </thead>
      <tbody>
        {#each singleRows as a}
          <tr
            class:uca-row={a.in_perimeter && !a.excluded}
            class:sg-excluded={a.excluded}
          >
            <td class="pos-cell">{(a.author_position ?? 0) + 1}</td>
            <td>
              {#if isAdmin}<button
                  class="exclude-btn"
                  title={a.excluded ? "Rétablir" : "Marquer comme faux"}
                  onclick={() => toggleExclude(singleSource, a)}
                  >{a.excluded ? "↩" : "×"}</button
                >{/if}
              {#if a.person_id}
                <a href="{base}/persons/{a.person_id}" class="author-link">
                  {a.full_name}
                </a>
              {:else}
                <span>{a.full_name}</span>
              {/if}
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
              {#if a.raw_affiliation}
                <span class="raw-affil">{a.raw_affiliation}</span>
              {/if}
            </td>
            <td>
              {#if a.countries}
                <span class="author-countries"
                  >{a.countries.map((c) => c.toUpperCase()).join(" ")}</span
                >
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .section {
    margin-bottom: 16px;
  }
  .section-title {
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 8px;
  }
  .source-details {
    margin-bottom: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .source-details :global(summary) {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    font-size: 0.95rem;
    font-weight: 500;
    cursor: pointer;
    background: #f5f4f1;
    border-bottom: 1px solid var(--border);
    user-select: none;
  }
  .source-details :global(summary:hover) {
    background: #eae9e5;
  }
  .source-details[open] > :global(summary) {
    margin-bottom: 0;
  }
  .source-ok {
    color: #2a7d4f;
  }
  .source-conflict {
    color: #c0392b;
  }
  .status-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    font-size: 0.75rem;
    font-weight: 700;
  }
  .ok-icon {
    background: var(--accent, #3b82f6);
    color: white;
  }
  .conflict-icon {
    background: #fde8e8;
    color: #c0392b;
  }
  .source-summary-count {
    font-size: 0.85rem;
    color: var(--muted);
    font-weight: 400;
  }
  .source-grid-wrap {
    overflow-x: auto;
  }
  .source-grid {
    width: 100%;
    border-collapse: collapse;
  }
  .source-grid :global(thead th) {
    background: #f5f4f1;
    padding: 6px 10px;
    text-align: left;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--muted);
    border-bottom: 2px solid var(--border);
    white-space: nowrap;
  }
  .source-grid tbody tr {
    border-bottom: 1px solid #f0efec;
  }
  .source-grid tbody tr:last-child {
    border-bottom: none;
  }
  .sg-pos {
    width: 28px;
    text-align: center;
  }
  .sg-name {
    min-width: 120px;
  }
  .sg-pos-cell {
    text-align: center;
    color: var(--muted);
    font-size: 0.8rem;
    padding: 4px 6px;
    vertical-align: middle;
  }
  .sg-name-cell {
    padding: 4px 10px;
    font-size: 0.88rem;
    vertical-align: middle;
    white-space: nowrap;
  }
  .countries-row {
    border-bottom: 2px solid var(--border) !important;
  }
  .countries-cell {
    font-size: 0.75rem;
    color: var(--muted);
    letter-spacing: 1px;
    padding: 3px 10px !important;
    white-space: normal !important;
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  .author-countries {
    font-size: 0.7rem;
    color: #888;
    margin-left: 4px;
    letter-spacing: 0.5px;
  }
  .sg-author-link {
    text-decoration: none;
    color: var(--accent);
  }
  .sg-author-link:hover {
    text-decoration: underline;
  }
  .sg-uca {
    font-weight: 600;
  }
  .sg-excluded {
    opacity: 0.4;
  }
  .sg-excluded a,
  .sg-excluded span {
    text-decoration: line-through;
  }
  .exclude-btn {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0 4px 0 0;
    font-size: 0.85rem;
    line-height: 1;
    color: #999;
    vertical-align: middle;
  }
  .exclude-btn:hover {
    color: #c0392b;
  }
  .conflict-row {
    background: #fff8f0;
  }
  .conflict-row:hover {
    background: #fef0e0;
  }
  .info-icon {
    cursor: help;
    color: var(--muted);
    font-size: 0.8rem;
    margin-left: 4px;
  }
  .info-icon:hover {
    color: var(--accent);
  }
  /* Single-source fallback : auth-table styles minimal */
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
  .uca-row {
    background: #f8fcf9;
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
    background: #e8f0f8;
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
  .raw-affil {
    font-size: 0.8rem;
    color: var(--muted);
    font-style: italic;
  }
</style>
