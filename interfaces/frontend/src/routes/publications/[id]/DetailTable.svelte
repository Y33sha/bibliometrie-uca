<script lang="ts">
  import type { Snippet } from "svelte";

  // Section titrée de la page de détail, en tableau de libellés (`dt`) et de valeurs (`dd`) fournis par le parent.
  const { title, children }: { title: string; children: Snippet } = $props();
</script>

<div class="section">
  <h2 class="section-title">{title}</h2>
  <dl class="detail-dl">
    {@render children()}
  </dl>
</div>

<style>
  .section {
    margin-bottom: 16px;
  }
  .section-title {
    margin-top: 0;
  }
  .detail-dl {
    display: grid;
    grid-template-columns: auto 1fr;
    font-size: var(--fs-md);
    margin: 0;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .detail-dl :global(dt),
  .detail-dl :global(dd) {
    padding: 7px 12px;
    border-bottom: 1px solid var(--border-subtle);
    margin: 0;
  }
  .detail-dl :global(dt) {
    font-weight: 600;
    color: var(--muted);
    white-space: nowrap;
    background: var(--surface-hover);
    font-size: var(--fs-sm);
  }
</style>
