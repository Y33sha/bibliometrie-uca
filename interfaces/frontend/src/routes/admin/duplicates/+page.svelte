<script lang="ts">
  import { api, duplicates } from "$lib/api";
  import { base } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/stores";
  import { onMount } from "svelte";
  import { sanitizeTitle, sourceExternalUrl } from "$lib/utils";
  import SourceTag from "$lib/components/SourceTag.svelte";

  import type { components } from "$lib/api/schema";
  type PubDetail = components["schemas"]["PubDedupDetail"];
  type NextResponse = components["schemas"]["PubDuplicateNextResponse"];

  // Restore state from URL
  const params = new URLSearchParams($page.url.search);
  let total = $state(0);
  let offset = $state(parseInt(params.get("offset") ?? "0") || 0);
  let pair = $state<{ pub_a: PubDetail; pub_b: PubDetail } | null>(null);
  let loading = $state(false);
  let acting = $state(false);
  let mergedCount = $state(0);
  let distinctCount = $state(0);
  let error = $state("");

  function syncUrl() {
    const p = new URLSearchParams();
    if (offset > 0) p.set("offset", String(offset));
    const qs = p.toString();
    replaceState(`${base}/admin/duplicates${qs ? "?" + qs : ""}`, {});
  }

  async function loadAt(pos: number) {
    loading = true;
    error = "";
    try {
      const data = await api<NextResponse>(`/api/admin/duplicates/next?offset=${pos}`);
      total = data.total;
      offset = data.offset;
      pair = data.pair;
      // Si l'offset dépasse le total (fin de liste), revenir au début
      if (!pair && total > 0 && pos > 0) {
        offset = 0;
        const data2 = await api<NextResponse>(`/api/admin/duplicates/next?offset=0`);
        total = data2.total;
        offset = data2.offset;
        pair = data2.pair;
      }
      syncUrl();
    } catch (e: any) {
      error = e.message || "Erreur de chargement";
      console.error(e);
    }
    loading = false;
  }

  async function mergePair(pubIdA: number, pubIdB: number) {
    acting = true;
    try {
      await duplicates.mergePublications({ pub_id_a: pubIdA, pub_id_b: pubIdB });
      mergedCount++;
      // Après fusion, la paire disparaît : même offset = paire suivante
      await loadAt(offset);
    } catch (e: any) {
      error = e.message || "Erreur de fusion";
      console.error(e);
    }
    acting = false;
  }

  async function markDistinct(pubIdA: number, pubIdB: number) {
    acting = true;
    try {
      await duplicates.markPublicationsDistinct({ pub_id_a: pubIdA, pub_id_b: pubIdB });
      distinctCount++;
      // Après marquage, la paire disparaît : même offset = paire suivante
      await loadAt(offset);
    } catch (e: any) {
      error = e.message || "Erreur";
      console.error(e);
    }
    acting = false;
  }

  onMount(() => {
    loadAt(offset);
  });
</script>

<svelte:head><title>Doublons publications — Admin</title></svelte:head>

<div class="container">
  <h1>Doublons de publications</h1>

  <div class="stats-bar">
    <div class="nav-group">
      <button class="btn btn-nav" onclick={() => loadAt(Math.max(0, offset - 1))} disabled={loading || offset === 0} title="Paire précédente">&lsaquo;</button>
      <span class="stat stat-position">{total > 0 ? offset + 1 : 0} / {total}</span>
      <button class="btn btn-nav" onclick={() => loadAt(offset + 1)} disabled={loading || !pair} title="Paire suivante">&rsaquo;</button>
    </div>
    {#if mergedCount}<span class="stat stat-merged">{mergedCount} fusionnée{mergedCount !== 1 ? "s" : ""}</span>{/if}
    {#if distinctCount}<span class="stat stat-distinct">{distinctCount} distincte{distinctCount !== 1 ? "s" : ""}</span>{/if}
  </div>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if loading}
    <p class="loading">Chargement…</p>
  {:else if !pair}
    <p class="empty">Aucun candidat doublon restant (titres normalisés identiques, &gt; 30 caractères).</p>
  {:else}
    {@const a = pair.pub_a}
    {@const b = pair.pub_b}

    <div class="pair-card">
      <!-- Titre normalisé commun -->
      <div class="shared-title">
        <span class="label">Titre normalisé :</span>
        {a.title_normalized}
      </div>

      <!-- Actions -->
      <div class="pair-actions">
        <button class="btn btn-merge" onclick={() => mergePair(a.id, b.id)} disabled={acting} title="Fusionner ces deux publications (métadonnées re-dérivées des sources)"> Fusionner </button>
        <button class="btn btn-distinct" onclick={() => markDistinct(a.id, b.id)} disabled={acting} title="Ces deux publications sont bien distinctes"> Marquer distincts </button>
        <button class="btn btn-skip" onclick={() => loadAt(offset + 1)} disabled={acting} title="Passer cette paire pour y revenir plus tard"> Passer &rsaquo; </button>
      </div>

      <!-- Deux colonnes -->
      <div class="pair-columns">
        {#each [a, b] as pub}
          <div class="pub-col">
            <div class="pub-sources">
              {#each pub.sources as src}
                <SourceTag source={src.source} href={sourceExternalUrl(src.source, src.source_id)} id={src.source_id} />
              {/each}
            </div>
            <div class="pub-meta">
              <span class="pub-type">{pub.doc_type ?? "?"}</span>
              <span class="pub-year">{pub.pub_year}</span>
              {#if pub.language}<span class="pub-lang">{pub.language}</span>{/if}
            </div>
            <div class="pub-title">
              <a href="{base}/publications/{pub.id}">{@html sanitizeTitle(pub.title)}</a>
            </div>
            {#if pub.doi}
              <div class="pub-doi">DOI: {pub.doi}</div>
            {/if}
            <div class="pub-journal">{pub.container_title ?? "—"}</div>
            {#if pub.journal}
              <div class="pub-journal-detail">
                {pub.journal.title}
                {#if pub.journal.issn}· ISSN {pub.journal.issn}{/if}
                {#if pub.journal.eissn}· eISSN {pub.journal.eissn}{/if}
              </div>
            {/if}
            <div class="pub-oa">OA : {pub.oa_status ?? "?"}</div>

            <h4>Auteurs ({pub.authors.length})</h4>
            <div class="author-list">
              {#each pub.authors as au}
                <div class="author-item" class:uca={au.in_perimeter}>
                  <span class="author-pos">{(au.author_position ?? 0) + 1}.</span>
                  {#if au.person_id}
                    <a href="{base}/persons/{au.person_id}" class="person-link-name">
                      {au.first_name ?? ""}
                      {au.last_name ?? "?"}
                    </a>
                  {:else}
                    <span>{au.full_name ?? au.first_name ?? ""} {au.last_name ?? "?"}</span>
                  {/if}
                </div>
              {/each}
            </div>

            <div class="source-ids">
              {#each pub.sources as src}
                <span class="source-detail">{src.source}: {src.source_id}</span>
              {/each}
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>

<style>
  .container {
    max-width: 1100px;
    margin: 0 auto;
    padding: 24px;
  }
  h1 {
    font-size: 1.5rem;
    margin-bottom: 16px;
  }

  .stats-bar {
    display: flex;
    gap: 12px;
    margin-bottom: 20px;
    align-items: center;
  }
  .stat {
    font-size: 0.9rem;
    padding: 4px 10px;
    background: #f5f5f5;
    border-radius: 4px;
    color: var(--muted, #666);
  }
  .stat-position {
    background: #e2e6ea;
    color: #333;
    font-weight: 600;
  }
  .stat-merged {
    background: var(--success-light);
    color: var(--success);
  }
  .stat-distinct {
    background: #fff3cd;
    color: #856404;
  }
  .nav-group {
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .pair-card {
    background: var(--card, #fff);
    border: 1px solid var(--border, #e0e0e0);
    border-radius: 8px;
    overflow: hidden;
  }
  .shared-title {
    padding: 10px 16px;
    background: #f0f4f8;
    border-bottom: 1px solid var(--border, #e0e0e0);
    font-size: 0.9rem;
  }
  .shared-title .label {
    font-weight: 600;
    color: var(--muted, #666);
  }

  .pair-columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  @media (max-width: 760px) {
    .pair-columns { grid-template-columns: 1fr; }
  }
  .pub-col {
    padding: 14px 16px;
  }
  .pub-col:first-child {
    border-right: 1px solid var(--border, #e0e0e0);
  }
  .pub-sources {
    display: flex;
    gap: 4px;
    margin-bottom: 6px;
  }
  .pub-meta {
    display: flex;
    gap: 8px;
    font-size: 0.8rem;
    color: var(--muted, #666);
    margin-bottom: 4px;
  }
  .pub-title {
    font-size: 0.95rem;
    margin-bottom: 4px;
  }
  .pub-title a {
    color: inherit;
    text-decoration: none;
  }
  .pub-title a:hover {
    text-decoration: underline;
  }
  .pub-doi {
    font-size: 0.8rem;
    color: var(--muted, #666);
    font-family: "SF Mono", SFMono-Regular, Consolas, monospace;
  }
  .pub-journal {
    font-size: 0.85rem;
    font-style: italic;
    color: var(--muted, #666);
    margin-top: 2px;
  }
  .pub-journal-detail {
    font-size: 0.75rem;
    color: var(--muted, #999);
  }
  .pub-oa {
    font-size: 0.8rem;
    color: var(--muted, #666);
    margin-top: 2px;
  }
  h4 {
    font-size: 0.85rem;
    margin: 10px 0 4px 0;
    color: var(--muted, #666);
  }
  .author-list {
    margin: 0 0 8px 0;
    font-size: 0.85rem;
  }
  .author-item {
    padding: 1px 0;
  }
  .author-item.uca {
    font-weight: 600;
  }
  .author-pos {
    display: inline-block;
    width: 24px;
    text-align: right;
    margin-right: 4px;
    color: var(--muted, #999);
    font-size: 0.8rem;
  }
  .person-link-name {
    color: var(--accent);
    text-decoration: none;
    font-size: 0.85rem;
  }
  .person-link-name:hover {
    text-decoration: underline;
  }
  .source-ids {
    margin-top: 6px;
  }
  .source-detail {
    display: block;
    font-size: 0.75rem;
    color: var(--muted, #999);
    font-family: monospace;
  }

  .pair-actions {
    display: flex;
    gap: 8px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border, #e0e0e0);
    background: #fafafa;
    justify-content: center;
  }
  .btn-merge,
  .btn-distinct,
  .btn-skip {
    padding: 8px 18px;
    font-size: 0.9rem;
  }

  .loading,
  .empty {
    text-align: center;
    color: var(--muted, #666);
    padding: 40px;
  }
  .error {
    color: var(--danger);
    padding: 8px 12px;
    background: var(--danger-light);
    border-radius: 4px;
    margin-bottom: 12px;
  }
</style>
