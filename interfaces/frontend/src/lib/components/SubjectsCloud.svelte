<script lang="ts">
  import { onMount } from "svelte";
  import { base } from "$app/paths";
  import cloud from "d3-cloud";
  import type { components } from "$lib/api/schema";

  type SubjectFrequency = components["schemas"]["SubjectFrequency"];

  interface CloudWord extends cloud.Word {
    id: number;
  }

  let { subjects }: { subjects: SubjectFrequency[] } = $props();

  let container: HTMLDivElement | undefined = $state();
  let width = $state(800);
  let height = $state(420);

  // Palette douce ; couleur stable par sujet via hash de l'id (palette
  // tournante). À garder visuelle, non-sémantique : on évite de mêler
  // type concept/libre ou ontologie pour ne pas surcharger le sens visuel.
  const PALETTE = ["#075985", "#0369a1", "#7c3aed", "#9333ea", "#be123c", "#b45309"];
  function colorFor(id: number): string {
    return PALETTE[id % PALETTE.length];
  }

  function fontSizeFor(count: number, minCount: number, maxCount: number): number {
    const minSize = 11;
    const maxSize = 32;
    if (maxCount === minCount) return (minSize + maxSize) / 2;
    const t =
      (Math.log10(count + 1) - Math.log10(minCount + 1)) /
      (Math.log10(maxCount + 1) - Math.log10(minCount + 1));
    return minSize + t * (maxSize - minSize);
  }

  let placedWords = $state<CloudWord[]>([]);
  let layoutDone = $state(false);

  function buildLayout() {
    if (!subjects.length) {
      placedWords = [];
      layoutDone = true;
      return;
    }
    const counts = subjects.map((s) => s.count);
    const minCount = Math.min(...counts);
    const maxCount = Math.max(...counts);
    const words: CloudWord[] = subjects.map((s) => ({
      text: s.label,
      size: fontSizeFor(s.count, minCount, maxCount),
      id: s.id,
    }));

    layoutDone = false;
    cloud<CloudWord>()
      .size([width, height])
      .words(words)
      .padding(3)
      // Texte horizontal uniquement : plus lisible et plus discret.
      .rotate(() => 0)
      .font("system-ui, sans-serif")
      .fontSize((d) => d.size!)
      .spiral("archimedean")
      .on("end", (placed: CloudWord[]) => {
        placedWords = placed;
        layoutDone = true;
      })
      .start();
  }

  function onResize() {
    if (container) {
      const rect = container.getBoundingClientRect();
      width = Math.max(400, rect.width);
      // Hauteur compacte : tous les mots sont horizontaux, pas la peine
      // de gaspiller de la hauteur sur du vide.
      height = Math.max(140, Math.round(rect.width * 0.22));
    }
    buildLayout();
  }

  // Re-layout à chaque changement de subjects ou de taille.
  $effect(() => {
    void subjects;
    if (container) buildLayout();
  });

  onMount(() => {
    onResize();
    const ro = new ResizeObserver(() => onResize());
    if (container) ro.observe(container);
    return () => ro.disconnect();
  });
</script>

<div bind:this={container} class="cloud-container">
  {#if subjects.length === 0}
    <p class="empty">Aucun sujet à afficher.</p>
  {:else}
    <svg {width} {height}>
      <g transform="translate({width / 2}, {height / 2})">
        {#each placedWords as w (w.id)}
          <a href="{base}/subjects/{w.id}">
            <text
              text-anchor="middle"
              font-family="system-ui, sans-serif"
              font-size={w.size}
              fill={colorFor(w.id)}
              transform={`translate(${w.x ?? 0}, ${w.y ?? 0})`}
              style="cursor: pointer;"
            >
              {w.text}
            </text>
          </a>
        {/each}
      </g>
    </svg>
    {#if !layoutDone}
      <p class="layout-loading">Mise en page…</p>
    {/if}
  {/if}
</div>

<style>
  .cloud-container {
    width: 100%;
    background: white;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px;
    overflow: hidden;
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
  }
  text {
    transition: opacity 0.15s;
  }
  text:hover {
    opacity: 0.7;
  }
  .empty,
  .layout-loading {
    color: var(--muted, #6b7280);
    font-style: italic;
    font-size: 0.9rem;
    margin: 0;
    padding: 12px;
  }
</style>
