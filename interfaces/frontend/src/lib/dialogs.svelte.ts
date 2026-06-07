/**
 * Dialogues UI globaux : confirmation (remplace `confirm()`) et toasts
 * (remplacent `alert()`). Un seul `<DialogHost>` monté dans le layout rend
 * l'état exposé ici.
 *
 * Usage :
 *   if (!(await confirmDialog({ message: '…', danger: true }))) return;
 *   toast('Enregistré', 'success');
 */

interface ConfirmOptions {
	message: string;
	title?: string;
	confirmLabel?: string;
	cancelLabel?: string;
	/** Bouton de confirmation en rouge (action destructive). */
	danger?: boolean;
}

interface ConfirmRequest extends ConfirmOptions {
	resolve: (ok: boolean) => void;
}

export type ToastType = 'success' | 'error' | 'info';
export interface ToastItem {
	id: number;
	message: string;
	type: ToastType;
}

let confirmRequest = $state<ConfirmRequest | null>(null);
let toasts = $state<ToastItem[]>([]);
let nextId = 0;

/** Lecture réactive pour `<DialogHost>` (getters → réactivité cross-module). */
export const dialogs = {
	get confirmRequest(): ConfirmRequest | null {
		return confirmRequest;
	},
	get toasts(): ToastItem[] {
		return toasts;
	}
};

/** Affiche une confirmation et résout `true`/`false` au choix de l'utilisateur. */
export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
	return new Promise((resolve) => {
		confirmRequest = { ...opts, resolve };
	});
}

export function resolveConfirm(ok: boolean): void {
	confirmRequest?.resolve(ok);
	confirmRequest = null;
}

export function toast(message: string, type: ToastType = 'info', ttlMs = 3500): void {
	const id = nextId++;
	toasts = [...toasts, { id, message, type }];
	setTimeout(() => dismissToast(id), ttlMs);
}

export function dismissToast(id: number): void {
	toasts = toasts.filter((t) => t.id !== id);
}
