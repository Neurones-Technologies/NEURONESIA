"use client";

import { useCallback, useSyncExternalStore } from "react";

const CHANGE_EVENT = "copilot:sidebar-pref";

/** Préférence « historique affiché / masqué », mémorisée par profil.
 *
 * `useSyncExternalStore` plutôt qu'un `useState` + `useEffect` de restauration :
 * le localStorage est un store externe, et cette forme donne un instantané
 * serveur explicite (panneau ouvert) — pas de rendu en cascade au montage, pas
 * d'écart d'hydratation. L'événement maison sert à notifier l'onglet courant,
 * `storage` ne se déclenchant que dans les *autres* onglets. */
export function useSidebarPref(key: string): [boolean, () => void] {
  const subscribe = useCallback((onChange: () => void) => {
    window.addEventListener("storage", onChange);
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => {
      window.removeEventListener("storage", onChange);
      window.removeEventListener(CHANGE_EVENT, onChange);
    };
  }, []);

  const getSnapshot = useCallback(() => localStorage.getItem(key) !== "closed", [key]);

  const open = useSyncExternalStore(subscribe, getSnapshot, () => true);

  const toggle = useCallback(() => {
    localStorage.setItem(key, localStorage.getItem(key) === "closed" ? "open" : "closed");
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, [key]);

  return [open, toggle];
}
