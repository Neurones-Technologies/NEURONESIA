"use client";

import { createContext, useCallback, useContext, useEffect, useState, ReactNode } from "react";
import { Variant } from "@/lib/types";

/** Fiche de détail ouverte dans le tiroir latéral. Uniquement des données
 * sérialisables : les vues sont des Server Components, elles passent l'objet
 * tel quel au wrapper client `Clickable`. */
export interface DetailCard {
  kicker?: string;
  title: string;
  tag?: string;
  tagVariant?: Variant;
  /** Paragraphes du corps — ce qui explique/corrobore le chiffre affiché. */
  body?: string | string[];
  /** Paires clé/valeur du tableau de corroboration : `[libellé, valeur]`.
   * Typé en tableau de chaînes (et non en tuple) pour que les vues puissent
   * composer la liste par `map`/spread sans annotation à chaque appel. */
  kv?: readonly (readonly string[])[];
  note?: string;
}

interface DetailCtx {
  open: (card: DetailCard) => void;
}

const Ctx = createContext<DetailCtx | null>(null);

export function DetailProvider({ children }: { children: ReactNode }) {
  const [card, setCard] = useState<DetailCard | null>(null);
  const [visible, setVisible] = useState(false);

  const open = useCallback((c: DetailCard) => {
    setCard(c);
    setVisible(true);
  }, []);

  const close = useCallback(() => setVisible(false), []);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [visible, close]);

  const paragraphs = card?.body ? (Array.isArray(card.body) ? card.body : [card.body]) : [];

  return (
    <Ctx.Provider value={{ open }}>
      {children}
      <div className={`ovl${visible ? " on" : ""}`} onClick={close} />
      <aside className={`drw${visible ? " on" : ""}`} role="dialog" aria-modal="true" aria-label="Détail">
        {card && (
          <>
            <div className="drw-h">
              <div className="drw-k">
                <span>{card.kicker ?? "Détail"}</span>
                <button className="drw-x" onClick={close} aria-label="Fermer le détail">
                  &times;
                </button>
              </div>
              <h3>{card.title}</h3>
              {card.tag && <span className={`tag tag--${card.tagVariant ?? "n"}`}>{card.tag}</span>}
            </div>
            <div className="drw-b">
              {paragraphs.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
              {card.kv && card.kv.length > 0 && (
                <div className="kv">
                  {card.kv.map((row, i) => (
                    <div key={i}>
                      <span>{row[0]}</span>
                      <b>{row[1]}</b>
                    </div>
                  ))}
                </div>
              )}
              {card.note && <p className="foot-n">{card.note}</p>}
            </div>
          </>
        )}
      </aside>
    </Ctx.Provider>
  );
}

function useDetail() {
  return useContext(Ctx);
}

/** Ouvre le tiroir depuis un composant client déjà interactif, là où `Clickable`
 * ne convient pas : un `<div role="button">` ne peut pas contenir un champ de
 * formulaire ni un autre bouton sans casser la navigation au clavier. C'est le
 * cas des cartes d'option du dossier d'arbitrage, qui portent un bouton radio.
 * Le tiroir reste accessible, mais par un vrai `<button>` distinct. */
export function DetailButton({
  detail,
  children,
  className = "linkish",
  title,
}: {
  detail: DetailCard;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  const ctx = useDetail();
  return (
    <button type="button" className={className} title={title} onClick={() => ctx?.open(detail)}>
      {children}
    </button>
  );
}

/** Rend ses enfants dans un élément cliquable qui ouvre le tiroir de détail.
 * Utilisable depuis un Server Component : `detail` doit rester sérialisable. */
export function Clickable({
  detail,
  className,
  as = "div",
  children,
  dataAttrs,
}: {
  detail: DetailCard;
  className?: string;
  as?: "div" | "tr";
  children: ReactNode;
  /** Attributs `data-*` bruts (ex. `{ "data-relevant": "false" }`) — permet à
   * un parent client de filtrer des lignes par CSS sans re-render ni state
   * porté ici. */
  dataAttrs?: Record<string, string>;
}) {
  const ctx = useDetail();
  const cls = `${className ?? ""} clk`.trim();
  const props = {
    className: cls,
    tabIndex: 0,
    role: "button" as const,
    onClick: () => ctx?.open(detail),
    onKeyDown: (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        ctx?.open(detail);
      }
    },
    ...dataAttrs,
  };
  return as === "tr" ? <tr {...props}>{children}</tr> : <div {...props}>{children}</div>;
}
