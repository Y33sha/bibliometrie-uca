<script lang="ts">
  import type { Snippet } from "svelte";

  // Éléments rejetés d'une personne, repliés sous un libellé « afficher… / masquer… ». Ils se replient à chaque changement de personne.
  let {
    personId,
    label,
    children,
  }: {
    personId: number;
    /** Éléments repliés, précédés de l'article : « les formes rejetées ». */
    label: string;
    children: Snippet;
  } = $props();

  let open = $state(false);

  $effect(() => {
    void personId;
    open = false;
  });
</script>

<details class="rejected-fold" bind:open>
  <summary>
    {open ? "masquer" : "afficher"} {label}
    <span class="chevron" class:up={open} aria-hidden="true"></span>
  </summary>
  {@render children()}
</details>

<style>
  .rejected-fold {
    margin-top: 8px;
  }
  .rejected-fold summary {
    /* Retire le triangle natif : la flèche fait partie du libellé. */
    list-style: none;
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  .rejected-fold summary::-webkit-details-marker {
    display: none;
  }
  .rejected-fold summary:hover {
    color: var(--accent);
  }
  .rejected-fold[open] summary {
    margin-bottom: 4px;
  }
</style>
