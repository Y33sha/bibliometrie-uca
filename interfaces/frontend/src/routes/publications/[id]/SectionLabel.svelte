<script lang="ts">
  // Label de section de la fiche détail : petite icône discrète (stroke = couleur du label) + texte.
  // Les tracés sont des icônes simples (style Feather), faciles à remplacer par les icônes finales.
  let {
    icon,
    text,
    count,
  }: {
    icon: "person" | "building" | "document" | "tag";
    text: string;
    count?: number;
  } = $props();
</script>

<div class="detail-label">
  <svg class="detail-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    {#if icon === "person"}
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    {:else if icon === "building"}
      <line x1="3" y1="21" x2="21" y2="21" />
      <path d="M3 10l9-6 9 6" />
      <line x1="6" y1="10" x2="6" y2="21" />
      <line x1="10" y1="10" x2="10" y2="21" />
      <line x1="14" y1="10" x2="14" y2="21" />
      <line x1="18" y1="10" x2="18" y2="21" />
    {:else if icon === "document"}
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
    {:else if icon === "tag"}
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" />
      <line x1="7" y1="7" x2="7.01" y2="7" />
    {/if}
  </svg>
  <span>{text}{#if count != null}&nbsp;({count}){/if}</span>
</div>

<style>
  .detail-label {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .detail-icon {
    width: 15px;
    height: 15px;
    opacity: 0.85;
    flex-shrink: 0;
  }
</style>
