import type { components } from "#lib/api/schema.js";
import { specificity } from "./specificity";

type SubjectListItem = components["schemas"]["SubjectListItem"];
type SubjectNeighbor = components["schemas"]["SubjectNeighborOut"];
type SubjectNeighborLink = components["schemas"]["SubjectNeighborLink"];

/**
 * Placement du graphe radial d'un sujet : le sujet au centre, ses voisins répartis tout autour sur une ellipse.
 *
 * - L'ordre des voisins autour du centre met côte à côte les sujets qui se rencontrent souvent.
 * - La distance au centre dépend de la spécificité de l'association : les plus spécifiques au plus près.
 * - Les recouvrements de cercles et de libellés se règlent en faisant glisser les voisins le long de leur ellipse. Quand la place manque, le graphe s'agrandit.
 * - L'ellipse s'arrondit quand la largeur disponible manque. Les libellés gardent leur taille.
 */

// Repère du placement, en pixels, centré sur le sujet central ; le cadre affiché (viewBox) épouse le graphe et ses libellés.
export const CX = 0;
export const CY = 0;
/** Étirements horizontaux de l'ellipse, du plus large au plus étroit. */
const STRETCHES = [1.6, 1.4, 1.2, 1, 0.8, 0.6];
/** Distance au centre des voisins les plus spécifiques, et écart jusqu'aux moins spécifiques, avant agrandissement du graphe faute de place. */
const INNER_RING = 60;
const RING_SPAN = 140;
/** Tailles de police, en unités du repère : libellés des voisins, titre du sujet central. */
export interface LabelSizes {
  label: number;
  center: number;
}
/** Interligne des libellés sur deux lignes, en proportion de la taille de police. */
const LINE_SPACING = 1.2;
/** Longueur au-delà de laquelle un libellé passe sur deux lignes. */
const MAX_LINE_LENGTH = 22;
/** Largeur approximative d'un libellé, en unités du repère, pour une taille de police donnée. */
const labelWidth = (label: string, fontSize: number) => label.length * fontSize * 0.54;

export interface GraphNode {
  neighbor: SubjectNeighbor;
  r: number;
  /** Libellé, sur une ou deux lignes. */
  lines: string[];
  /** Largeur de la plus longue ligne. */
  labelWidth: number;
  /** Demi-hauteur du libellé. */
  labelHalfHeight: number;
  /** Distance au centre, mesurée sur l'ellipse. */
  distance: number;
  x: number;
  y: number;
}

export interface Box {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** Rayon d'un cercle selon le nombre de publications du sujet (aire proportionnelle). */
function radius(usage: number, maxUsage: number): number {
  return 5 + (Math.sqrt(usage) / Math.sqrt(maxUsage)) * 17;
}

/** Libellé trop long coupé en deux lignes, à l'espace le plus proche du milieu. */
function labelLines(label: string): string[] {
  if (label.length <= MAX_LINE_LENGTH) return [label];
  const middle = label.length / 2;
  let cut = -1;
  for (let i = label.indexOf(" "); i >= 0; i = label.indexOf(" ", i + 1)) {
    if (cut < 0 || Math.abs(i - middle) < Math.abs(cut - middle)) cut = i;
  }
  return cut < 0 ? [label] : [label.slice(0, cut), label.slice(cut + 1)];
}

/** Emprise d'un voisin : son cercle et son libellé, placé du côté extérieur du graphe. */
export function nodeBox(n: GraphNode): Box {
  const half = Math.max(n.r, n.labelHalfHeight);
  return n.x >= CX
    ? { x0: n.x - n.r, x1: n.x + n.r + 6 + n.labelWidth, y0: n.y - half, y1: n.y + half }
    : { x0: n.x - n.r - 6 - n.labelWidth, x1: n.x + n.r, y0: n.y - half, y1: n.y + half };
}

/** Place un voisin sur l'ellipse d'étirement et de distance donnés (par défaut la sienne), à l'angle donné. */
function placeAt(n: GraphNode, angle: number, stretch: number, distance = n.distance): void {
  n.x = CX + Math.cos(angle) * distance * stretch;
  n.y = CY + Math.sin(angle) * distance;
}

/** Angle d'un voisin sur une ellipse d'étirement donné. */
function angleOf(n: GraphNode, stretch: number): number {
  return Math.atan2(n.y - CY, (n.x - CX) / stretch);
}

/**
 * Ordre circulaire des voisins qui maximise la proximité entre voisins consécutifs : chaîne gloutonne depuis le voisin le plus fréquent, puis améliorations par inversion de segments (2-opt).
 */
function circularOrder(nodes: GraphNode[], sim: (a: GraphNode, b: GraphNode) => number): GraphNode[] {
  const remaining = [...nodes].sort((a, b) => b.neighbor.cooccurrence_count - a.neighbor.cooccurrence_count);
  const order: GraphNode[] = [remaining.shift()!];
  while (remaining.length) {
    const last = order[order.length - 1];
    let best = 0;
    for (let i = 1; i < remaining.length; i++) if (sim(last, remaining[i]) > sim(last, remaining[best])) best = i;
    order.push(...remaining.splice(best, 1));
  }
  const n = order.length;
  let improved = true;
  while (improved && n > 3) {
    improved = false;
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 2; j < n; j++) {
        if (i === 0 && j === n - 1) continue;
        const a = order[i];
        const b = order[i + 1];
        const c = order[j];
        const d = order[(j + 1) % n];
        if (sim(a, c) + sim(b, d) > sim(a, b) + sim(c, d) + 1e-12) {
          order.splice(i + 1, j - i, ...order.slice(i + 1, j + 1).reverse());
          improved = true;
        }
      }
    }
  }
  return order;
}

/**
 * Placements du graphe d'un sujet, un par étirement de l'ellipse. La fonction renvoyée donne le placement le plus étiré qui tient dans une largeur donnée, sinon le plus étroit. Chaque placement se calcule à sa première demande.
 */
export function subjectGraphLayout(
  subject: SubjectListItem,
  neighbors: SubjectNeighbor[],
  links: SubjectNeighborLink[],
  sizes: LabelSizes,
) {
  const lineHeight = sizes.label * LINE_SPACING;
  const maxUsage = Math.max(subject.usage_count, ...neighbors.map((n) => n.usage_count), 1);
  const maxCooc = Math.max(...neighbors.map((n) => n.cooccurrence_count), 1);
  const specs = neighbors.map(specificity);
  const logMin = Math.log(Math.min(...specs));
  const logMax = Math.log(Math.max(...specs));
  // Distance au centre : l'anneau intérieur pour les plus spécifiques, puis un écart croissant quand la spécificité baisse, en échelle log pour ne pas écraser les faibles spécificités.
  const distanceOf = (spec: number) => {
    const t = logMax === logMin ? 0.5 : (Math.log(spec) - logMin) / (logMax - logMin);
    return INNER_RING + RING_SPAN * (1 - t);
  };
  const nodes: GraphNode[] = neighbors.map((n, i) => {
    const lines = labelLines(n.label);
    return {
      neighbor: n,
      r: radius(n.usage_count, maxUsage),
      lines,
      labelWidth: Math.max(...lines.map((line) => labelWidth(line, sizes.label))),
      labelHalfHeight: sizes.label * 0.7 + ((lines.length - 1) * lineHeight) / 2,
      distance: distanceOf(specs[i]),
      x: CX,
      y: CY,
    };
  });
  const byLabel = new Map(nodes.map((n) => [n.neighbor.label_normalized, n]));

  // Proximité de deux voisins : leurs publications en commun, rapportées à la moyenne géométrique de leurs tailles.
  const similarity = new Map<string, number>();
  const pairKey = (a: string, b: string) => (a < b ? `${a}|${b}` : `${b}|${a}`);
  for (const l of links) {
    const a = byLabel.get(l.label_a);
    const b = byLabel.get(l.label_b);
    if (a && b) similarity.set(pairKey(l.label_a, l.label_b), l.cooccurrence_count / Math.sqrt(a.neighbor.usage_count * b.neighbor.usage_count));
  }
  const sim = (a: GraphNode, b: GraphNode) =>
    similarity.get(pairKey(a.neighbor.label_normalized, b.neighbor.label_normalized)) ?? 0;

  const order = circularOrder(nodes, sim);
  const baseDistance = new Map(nodes.map((n) => [n, n.distance]));

  // Le sujet central et son titre, placé dessous, forment une emprise fixe que les voisins contournent.
  const centerR = radius(subject.usage_count, maxUsage) + 4;
  const centerLabelHalf = labelWidth(subject.label, sizes.center) / 2;
  const centerBox: Box = {
    x0: CX - Math.max(centerLabelHalf, centerR),
    x1: CX + Math.max(centerLabelHalf, centerR),
    y0: CY - centerR,
    y1: CY + centerR + 24,
  };
  const strokeWidth = (cooc: number) => 1 + (cooc / maxCooc) * 6;

  // Recouvrements : on écarte les emprises le long de l'axe du moindre recouvrement, puis chaque voisin revient sur son ellipse en gardant son nouvel angle. Renvoie vrai si plus rien ne se recouvre.
  const gap = 4;
  function relax(stretch: number): boolean {
    for (let pass = 0; pass < 300; pass++) {
      let moved = false;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j <= nodes.length; j++) {
          const b = j < nodes.length ? nodes[j] : null;
          const ba = nodeBox(a);
          const bb = b ? nodeBox(b) : centerBox;
          const ox = Math.min(ba.x1, bb.x1) - Math.max(ba.x0, bb.x0) + gap;
          const oy = Math.min(ba.y1, bb.y1) - Math.max(ba.y0, bb.y0) + gap;
          if (ox <= 0 || oy <= 0) continue;
          moved = true;
          const share = b ? 0.5 : 1;
          if (ox < oy) {
            const sign = (ba.x0 + ba.x1) / 2 < (bb.x0 + bb.x1) / 2 ? -1 : 1;
            a.x += sign * ox * share;
            if (b) b.x -= sign * ox * share;
          } else {
            const sign = (ba.y0 + ba.y1) / 2 < (bb.y0 + bb.y1) / 2 ? -1 : 1;
            a.y += sign * oy * share;
            if (b) b.y -= sign * oy * share;
          }
        }
      }
      // Retour vers l'ellipse : chaque voisin garde son nouvel angle et peut s'écarter un peu de sa distance théorique, ce qui règle les recouvrements sur place.
      for (const n of nodes) {
        const actual = Math.hypot((n.x - CX) / stretch, n.y - CY);
        placeAt(n, angleOf(n, stretch), stretch, Math.min(Math.max(actual, n.distance * 0.85), n.distance * 1.35));
      }
      if (!moved) return true;
    }
    return false;
  }

  function place(stretch: number) {
    // Répartition régulière tout autour du centre, dans l'ordre de proximité. Quand la place manque, toutes les distances au centre grandissent par paliers, dans la même proportion : l'ordre des distances ne change pas.
    for (let scale = 1; scale < 3; scale *= 1.1) {
      for (const n of nodes) n.distance = baseDistance.get(n)! * scale;
      order.forEach((n, i) => placeAt(n, -Math.PI / 2 + (2 * Math.PI * i) / order.length, stretch));
      if (relax(stretch)) break;
    }
    // Copie : les voisins de travail servent aux placements suivants.
    const placed = nodes.map((n) => ({ ...n }));

    // Cadre englobant cercles et libellés, avec une marge.
    let { x0: minX, x1: maxX, y0: minY, y1: maxY } = centerBox;
    for (const n of placed) {
      const b = nodeBox(n);
      minX = Math.min(minX, b.x0);
      maxX = Math.max(maxX, b.x1);
      minY = Math.min(minY, b.y0);
      maxY = Math.max(maxY, b.y1);
    }
    const pad = 12;
    const box = { x: minX - pad, y: minY - pad, width: maxX - minX + 2 * pad, height: maxY - minY + 2 * pad };

    return { nodes: placed, box, centerBox, centerR, strokeWidth, lineHeight };
  }

  const placements = new Map<number, ReturnType<typeof place>>();
  const placement = (stretch: number) => {
    if (!placements.has(stretch)) placements.set(stretch, place(stretch));
    return placements.get(stretch)!;
  };
  return (maxWidth: number) => {
    for (const stretch of STRETCHES) {
      const p = placement(stretch);
      if (p.box.width <= maxWidth) return p;
    }
    return STRETCHES.map(placement).reduce((a, b) => (b.box.width < a.box.width ? b : a));
  };
}
