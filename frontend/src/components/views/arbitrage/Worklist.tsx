"use client";

import Link, { useLinkStatus } from "next/link";
import { useMemo, useState } from "react";

import type { DetailCard } from "@/components/ui/detail";
import { DetailButton } from "@/components/ui/detail";
import { Tag } from "@/components/ui/primitives";
import { formatNumber } from "@/lib/format";
import { Variant } from "@/lib/types";

/** Une ligne de la file de travail. Tout est déjà mis en forme côté serveur :
 * ce composant ne connaît que des chaînes et quatre nombres pour trier. */
export interface QueueItem {
  ref: string;
  /** Phrase complète du dossier — sert à la recherche et aux libellés d'aide. */
  label: string;
  /** Nom du client seul, balayable d'un coup d'œil. */
  client: string;
  /** Nature du conflit : « 7 facture(s) échue(s) contre cross-sell en cours ». */
  conflit: string;
  /** Rang dans la file complète, ordre de priorité rendu par le backend. */
  rang: number;
  prioriteLabel: string;
  prioriteNiveau: number;
  prioriteRaison: string;
  payeurLabel: string;
  payeurVariant: Variant;
  trajectoire: string;
  mandatLabel: string;
  /** Sigle du mandataire — « Direction générale » ne tient pas dans la colonne. */
  mandatCourt: string;
  impayeM: number;
  enjeuM: number;
  retardMax: number;
  /** Le profil courant est-il mandataire ou partie citée sur ce dossier ? */
  relevant: boolean;
  detail: DetailCard;
}

type Tri = "priorite" | "enjeu" | "impaye" | "retard";

const TRI_LABELS: Record<Tri, string> = {
  priorite: "Priorité de traitement",
  enjeu: "Enjeu commercial",
  impaye: "Impayé constaté",
  retard: "Retard le plus ancien",
};

/** File de travail des conflits détectés — colonne de gauche de l'écran.
 *
 * Elle remplace l'ancien tableau posé SOUS le dossier : la file était alors une
 * liste à lire, pas un endroit d'où travailler, et un seul dossier (le premier
 * du périmètre) pouvait être instruit. Choisir sa ligne pose maintenant
 * `?dossier=<ref>` dans l'URL — le dossier est donc partageable, retrouvable au
 * rechargement, et le bouton Précédent du navigateur ramène au dossier
 * précédent au lieu de sortir de l'écran.
 *
 * Le libellé dit « Mon périmètre » et non « Mes comptes » à dessein : le filtre
 * porte sur le RÔLE impliqué dans le dossier (mandat + positions citées), pas sur
 * le portefeuille de comptes de l'utilisateur — le miroir ne rattache pas les
 * dossiers d'arbitrage à un commercial nommé. Promettre « mes comptes » ferait
 * croire à tort qu'un compte absent de la liste est sans tension. */
export function Worklist({
  items,
  selectedRef,
  basePath,
  perimeterLabel,
}: {
  items: QueueItem[];
  selectedRef: string | null;
  /** Chemin de la vue, ex. `/df/arbitrage` — la sélection s'y ajoute en query. */
  basePath: string;
  perimeterLabel: string;
}) {
  const nbRelevant = useMemo(() => items.filter((i) => i.relevant).length, [items]);
  // Aucun dossier dans le périmètre : on ouvre sur « Tous » plutôt que sur une
  // liste vide que rien n'expliquerait.
  const [showAll, setShowAll] = useState(nbRelevant === 0);
  const [query, setQuery] = useState("");
  const [tri, setTri] = useState<Tri>("priorite");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = items.filter((i) => {
      if (!showAll && !i.relevant) return false;
      if (!q) return true;
      return `${i.label} ${i.ref} ${i.payeurLabel} ${i.mandatLabel}`.toLowerCase().includes(q);
    });
    const sorted = [...filtered];
    if (tri === "enjeu") sorted.sort((a, b) => b.enjeuM - a.enjeuM);
    else if (tri === "impaye") sorted.sort((a, b) => b.impayeM - a.impayeM);
    else if (tri === "retard") sorted.sort((a, b) => b.retardMax - a.retardMax);
    else sorted.sort((a, b) => a.rang - b.rang);
    return sorted;
  }, [items, showAll, query, tri]);

  return (
    <div className="arb-queue">
      <div className="arb-queue-h">
        <h3>File d&apos;arbitrage</h3>
        <span className="tile-k">{formatNumber(items.length)} conflits détectés</span>
      </div>

      <div className="arb-seg" role="group" aria-label="Périmètre de la file">
        <button
          type="button"
          aria-pressed={!showAll}
          disabled={nbRelevant === 0}
          onClick={() => setShowAll(false)}
          title={
            nbRelevant === 0
              ? "Aucun dossier ne cite votre rôle actuellement"
              : `Dossiers où ${perimeterLabel} est mandataire ou partie prenante`
          }
        >
          Mon périmètre <i>{formatNumber(nbRelevant)}</i>
        </button>
        <button type="button" aria-pressed={showAll} onClick={() => setShowAll(true)}>
          Tous <i>{formatNumber(items.length)}</i>
        </button>
      </div>

      <div className="arb-tools">
        <div className="arb-search">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filtrer par client…"
            aria-label="Filtrer la file par client"
          />
        </div>
        <label className="arb-sort">
          <span className="sr-only">Trier la file</span>
          <select className="sel" value={tri} onChange={(e) => setTri(e.target.value as Tri)} aria-label="Trier la file">
            {(Object.keys(TRI_LABELS) as Tri[]).map((k) => (
              <option key={k} value={k}>
                Tri : {TRI_LABELS[k]}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="arb-queue-s">
        {showAll
          ? "Tous les dossiers ouverts, quel que soit le profil concerné."
          : `Dossiers où ${perimeterLabel} est mandataire ou partie prenante. Filtre par rôle, pas par portefeuille : le miroir ne rattache pas un dossier d'arbitrage à un commercial nommé.`}
      </p>

      {visible.length === 0 ? (
        <p className="arb-empty">
          {query.trim()
            ? `Aucun dossier ne correspond à « ${query.trim()} ».`
            : showAll
              ? "Aucun conflit détecté : aucun client en retard de paiement ne cumule un signal commercial actif."
              : "Aucun dossier ne cite votre rôle. Basculez sur « Tous » pour voir la file entière."}
        </p>
      ) : (
        <ul className="arb-list">
          {visible.map((it) => {
            const on = it.ref === selectedRef;
            return (
              <li key={it.ref} className={`arb-row${on ? " is-on" : ""}`}>
                <Link
                  href={`${basePath}?dossier=${encodeURIComponent(it.ref)}`}
                  scroll={false}
                  prefetch={false}
                  className="arb-item"
                  aria-current={on ? "true" : undefined}
                  title={it.label}
                >
                  <span className="arb-item-r">{String(it.rang).padStart(2, "0")}</span>
                  <span className="arb-item-b">
                    <span className="arb-item-n">{it.client}</span>
                    {it.conflit && <span className="arb-item-c">{it.conflit}</span>}
                    <span className="arb-item-t" title={it.prioriteRaison}>
                      <Tag
                        variant={
                          it.prioriteNiveau >= 3 ? "r" : it.prioriteNiveau === 2 ? "w" : it.prioriteNiveau === 1 ? "n" : "s"
                        }
                      >
                        {it.prioriteLabel}
                      </Tag>
                      <span className={`tag tag--${it.payeurVariant}`}>{it.payeurLabel}</span>
                    </span>
                    <span className="arb-item-m">
                      <i>impayé</i> {formatNumber(it.impayeM)} M<em>·</em>
                      <i>enjeu</i> {formatNumber(it.enjeuM)} M<em>·</em>
                      <i>mandat</i> {it.mandatCourt}
                    </span>
                    <span className="arb-item-s">{it.trajectoire}</span>
                  </span>
                  <LoadHint />
                </Link>
                <DetailButton
                  detail={it.detail}
                  className="arb-row-i"
                  title={`Chiffres du dossier ${it.label} — sans ouvrir l'instruction`}
                >
                  <span aria-hidden="true">i</span>
                  <span className="sr-only">Détail chiffré de {it.label}</span>
                </DetailButton>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Le dossier se charge en attendant deux appels au modèle (avocat du contraire,
 * formulation de l'échéancier) : sans repère, le clic paraît sans effet pendant
 * plusieurs secondes. Le point pulse tant que la navigation n'a pas abouti. */
function LoadHint() {
  const { pending } = useLinkStatus();
  return <span className={`arb-load${pending ? " on" : ""}`} aria-hidden="true" />;
}
