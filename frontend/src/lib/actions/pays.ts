"use server";

import { cookies } from "next/headers";
import { revalidatePath } from "next/cache";

/** Périmètre choisi par un compte GROUPE (sélecteur de l'en-tête).
 *
 * Écrit dans un cookie `pays` que `apiFetch` transmet au backend (en-tête
 * `X-Pays`). Ce n'est qu'une PRÉFÉRENCE : pour un compte rattaché à un pays, le
 * DG et l'admin, le backend ignore la valeur — le périmètre imposé se décide
 * côté serveur, jamais dans le navigateur. `httpOnly` : aucun script de page n'a
 * à la lire. « Groupe » efface le cookie. */
export async function choisirPaysAction(pays: string): Promise<void> {
  const store = await cookies();
  const valeur = (pays || "").trim().toUpperCase();
  if (["CI", "BF", "GN"].includes(valeur)) {
    store.set("pays", valeur, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 60 * 60 * 24 * 180,
    });
  } else {
    store.delete("pays");
  }
  // Toutes les pages lisent leurs chiffres sous ce périmètre : on les recalcule.
  revalidatePath("/", "layout");
}
