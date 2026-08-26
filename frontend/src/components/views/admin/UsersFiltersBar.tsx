"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useTransition } from "react";

import type { UsersFilters } from "@/lib/api/admin";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { adminHref } from "@/components/views/admin/href";

/** Filtres de la liste des comptes.
 *
 * Ils écrivent dans l'URL et non dans un state local, parce que c'est le SERVEUR
 * qui filtre (`GET /v1/auth/users?q=&role=&actif=`) : la liste rendue est
 * exactement celle qu'il a renvoyée. Un filtrage à l'écran aurait été plus simple
 * mais aurait menti dès que la liste dépasse ce qu'une page renvoie.
 *
 * La recherche est différée de 350 ms : sans cela, chaque frappe déclenche un
 * rendu serveur complet de l'écran (liste + matrice + journal). Le champ reste
 * piloté localement pendant la frappe pour ne pas perdre le curseur à chaque
 * navigation, et `useTransition` permet d'annoncer l'attente au lieu de figer.
 *
 * `replace` et non `push` : vingt frappes ne doivent pas laisser vingt entrées
 * dans l'historique, sinon le bouton Retour ne ramène plus à l'écran précédent.
 */
export function UsersFiltersBar({
  profile,
  filters,
  roles,
}: {
  profile: string;
  filters: UsersFilters;
  roles: string[];
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [q, setQ] = useState(filters.q ?? "");
  const rechercheId = useId();
  const roleId = useId();
  const statutId = useId();

  // La valeur venue de l'URL reprend la main quand elle change sans passer par
  // ce champ (bouton Retour, lien « effacer les filtres »).
  const externe = filters.q ?? "";
  const dernierExterne = useRef(externe);
  useEffect(() => {
    if (externe !== dernierExterne.current) {
      dernierExterne.current = externe;
      setQ(externe);
    }
  }, [externe]);

  // La fiche ouverte (`compte`) est délibérément abandonnée à chaque filtrage :
  // filtrer, c'est revenir à la liste.
  function naviguer(suivants: UsersFilters) {
    startTransition(() => router.replace(adminHref(profile, suivants), { scroll: false }));
  }

  useEffect(() => {
    const courant = filters.q ?? "";
    const saisi = q.trim();
    if (saisi === courant) return;
    const t = setTimeout(() => naviguer({ ...filters, q: saisi || undefined }), 350);
    return () => clearTimeout(t);
    // `filters` et `q` suffisent : `naviguer` ne fait que refermer sur eux.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, filters.q, filters.role, filters.actif]);

  const actifValue = filters.actif === undefined ? "" : filters.actif ? "oui" : "non";
  const filtre = Boolean(filters.q || filters.role || filters.actif !== undefined);

  return (
    // Trois champs sur une rangée : `.fld` est une grille `1fr auto` faite pour
    // « libellé à gauche, valeur à droite », pas pour une barre de filtres.
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 14,
        alignItems: "flex-end",
        padding: "10px 0 4px",
      }}
    >
      <div className="fgrp" style={{ marginBottom: 0, flex: "2 1 220px" }}>
        <label htmlFor={rechercheId}>Rechercher</label>
        <input
          id={rechercheId}
          type="search"
          value={q}
          placeholder="Nom ou adresse e-mail"
          autoComplete="off"
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      <div className="fgrp" style={{ marginBottom: 0, flex: "1 1 170px" }}>
        <label htmlFor={roleId}>Rôle</label>
        <select
          id={roleId}
          value={filters.role ?? ""}
          onChange={(e) => naviguer({ ...filters, role: e.target.value || undefined })}
        >
          <option value="">Tous les rôles</option>
          {roles.map((role) => (
            <option key={role} value={role}>
              {ROLE_LABELS[role] ?? role}
            </option>
          ))}
        </select>
      </div>

      <div className="fgrp" style={{ marginBottom: 0, flex: "1 1 170px" }}>
        <label htmlFor={statutId}>Statut</label>
        <select
          id={statutId}
          value={actifValue}
          onChange={(e) =>
            naviguer({
              ...filters,
              actif: e.target.value === "" ? undefined : e.target.value === "oui",
            })
          }
        >
          <option value="">Actifs et désactivés</option>
          <option value="oui">Actifs seulement</option>
          <option value="non">Désactivés seulement</option>
        </select>
      </div>

      <div className="acts" style={{ margin: 0 }}>
        <span className="ro" role="status" aria-live="polite">
          {pending ? "filtrage…" : filtre ? "filtres appliqués par le serveur" : ""}
        </span>
        {filtre && (
          <button
            type="button"
            className="btn"
            onClick={() => {
              setQ("");
              naviguer({});
            }}
          >
            Tout afficher
          </button>
        )}
      </div>
    </div>
  );
}
