/** Helpers partagés de la page pipeline : couleurs de statut, formatage. */

export type Status = "ok" | "warning" | "error";

export const STATUS_LABEL: Record<Status, string> = {
  ok: "OK",
  warning: "Avertissement",
  error: "Erreur",
};

// Couleurs sémantiques (indépendantes du thème) pour les cases du ruban et les pastilles.
export const CELL_COLOR: Record<Status | "ghost", string> = {
  ok: "#1a7f37",
  warning: "#9a6700",
  error: "#c0392b",
  ghost: "var(--border)",
};

export const CELL_BG: Record<Status | "ghost", string> = {
  ok: "#d8f0dd",
  warning: "#fff0c2",
  error: "#fbe0dd",
  ghost: "transparent",
};

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtDuration(s: number): string {
  if (s < 60) return `${s.toFixed(0)} s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s - m * 60);
  if (m < 60) return `${m} min ${rs} s`;
  const h = Math.floor(m / 60);
  return `${h} h ${m - h * 60} min`;
}

export function fmtRatio(v: number | null): string {
  return v === null ? "—" : v.toFixed(2);
}

// Repère visuel : une phase nettement plus lente que son médian historique.
export const SLOW_RATIO = 1.5;

export function isSlow(ratio: number | null): boolean {
  return ratio !== null && ratio >= SLOW_RATIO;
}
