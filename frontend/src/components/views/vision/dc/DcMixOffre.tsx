import { getOfferMix } from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Note } from "@/components/ui/primitives";

/** Page « Mix d'offre » — conservée pour son URL.
 *
 * Son entrée de menu est commentée (cf. lib/data/sections.ts) et ses tuiles sont
 * désormais affichées dans « Diagnostic ». La page reste servie parce que
 * `/dc/vision/mix-offre` a circulé en lien : elle doit continuer d'ouvrir son
 * contenu plutôt que de tomber en 404. */
export async function DcMixOffre() {
  return (
    <Bento>
      <DcMixOffreTuiles />
    </Bento>
  );
}

/** Tuiles du mix d'offre, SANS leur grille — pour être composées dans le `Bento`
 * d'un autre écran.
 *
 * Le mix a été replié dans « Diagnostic » (cf. DcTransformation) : ses deux
 * tuiles y prennent place parmi les autres plutôt que dans une grille imbriquée,
 * qui aurait rompu l'alignement sur douze colonnes. C'est la seule raison de
 * cette séparation — le contenu est inchangé.
 *
 * La famille est déduite du libellé de l'opportunité (Odoo ne porte aucune
 * catégorie sur crm.lead) : les parts affichées portent sur le pipe CLASSÉ, et
 * `couvertureMontant` doit rester visible partout où elles apparaissent. */
export async function DcMixOffreTuiles() {
  const offerMix = await getOfferMix();

  const mixFamilies = offerMix.families.filter((f) => f.nb > 0);
  const topFamilyMontant = mixFamilies[0]?.montant_xof ?? 0;
  const couvertureMontant = offerMix.coverage.couverture_montant_pct;
  const couvertureFaible = couvertureMontant < 70;
  // Trimestres à échéance future : les seuls à pouvoir se lire comme un
  // atterrissage. Sur ce pipe, l'essentiel du montant est déjà échu.
  const periodesAffichees = offerMix.periods.filter((p) => !p.vide);
  const partEchu = offerMix.echu.part_montant_pct;

  if (mixFamilies.length === 0) {
    return (
      <Tile span={12} title="Mix d'offre du pipeline">
        <Note style={{ marginTop: 0 }}>
          Aucune opportunité du pipe ouvert ne porte un libellé permettant d&apos;en déduire la famille
          d&apos;offre.
        </Note>
      </Tile>
    );
  }

  return (
    <>
      {/* Les deux tuiles du mix partagent une rangée (6 + 6) : elles se lisent
          ensemble — sur quoi le pipe se positionne, et sur quelles échéances il
          atterrit. En pleine largeur chacune, elles occupaient deux écrans. */}
      <Tile
        span={6}
        title="Mix d'offre du pipeline"
        kick={`calculé sur ${formatPct(couvertureMontant, 0)} % du pipe`}
        aide="La répartition de vos affaires en cours entre vos différentes offres. Montre si votre activité future repose sur une seule ligne ou sur plusieurs."
      >
        {/* La famille dominante ouvre la carte en `.stat-block` interne plutôt
            qu'en tuile séparée : c'est la lecture en une ligne du classement qui
            la suit, pas un indicateur autonome. */}
        <Clickable
          className="stat-block"
          detail={{
            kicker: "Indicateur · positionnement commercial",
            title: `${offerMix.dominante.label ?? "—"}, famille dominante du pipe`,
            tag: `${formatPct(offerMix.dominante.part_montant_pct, 0)} % du pipe qualifié`,
            tagVariant: "a",
            body: [
              `Le pipe ouvert qualifié se répartit entre ${mixFamilies.length} familles d'offre, dominé par ${offerMix.dominante.label ?? "—"} à ${formatPct(offerMix.dominante.part_montant_pct, 0)} % du montant.`,
              offerMix.dominante.delta_part_pct !== null
                ? `Sur le trimestre d'échéance courant, cette part varie de ${offerMix.dominante.delta_part_pct > 0 ? "+" : ""}${formatPct(offerMix.dominante.delta_part_pct, 1)} point(s) par rapport au trimestre précédent.`
                : "La variation trimestrielle n'est pas affichée : les trimestres comparés ne portent pas assez d'opportunités pour qu'un écart de part soit autre chose que du bruit d'échantillon.",
              `La famille est déduite du libellé de l'opportunité, faute de champ catégorie dans Odoo. ${formatNumber(offerMix.coverage.nb_non_classe)} opportunités sur ${formatNumber(offerMix.coverage.nb_total)} restent non qualifiables : les parts affichées portent sur ${formatPct(couvertureMontant, 0)} % du pipe en montant, et un libellé plus explicite dans Odoo est le seul moyen de faire monter ce chiffre.`,
            ],
            kv: [
              ["Famille dominante", offerMix.dominante.label ?? "—"],
              ["Part du pipe qualifié", `${formatPct(offerMix.dominante.part_montant_pct, 0)} %`],
              [
                "Variation trimestrielle",
                offerMix.dominante.delta_part_pct !== null
                  ? `${offerMix.dominante.delta_part_pct > 0 ? "+" : ""}${formatPct(offerMix.dominante.delta_part_pct, 1)} pt`
                  : "non significative",
              ],
              ["Couverture en montant", `${formatPct(couvertureMontant, 0)} %`],
              ["Couverture en nombre", `${formatPct(offerMix.coverage.couverture_nb_pct, 0)} %`],
              ["Opportunités non qualifiées", formatNumber(offerMix.coverage.nb_non_classe)],
            ],
            // note: "Le cockpit ne devine pas la famille : il la lit dans le libellé. Renseigner explicitement l'offre dans Odoo est ce qui fait progresser la couverture.",
          }}
        >
          <div className="tile-h">
            <h3>Famille dominante</h3>
          </div>
          <div>
            <span className="stat-v num">{offerMix.dominante.label ?? "—"}</span>
            <span className="stat-u">{formatPct(offerMix.dominante.part_montant_pct, 0)} % du pipe qualifié</span>
          </div>
          <div className={`stat-d${couvertureFaible ? " wat" : ""}`}>
            {couvertureFaible
              ? `couverture faible : ${formatPct(couvertureMontant, 0)} % du pipe classé`
              : `sur ${formatPct(couvertureMontant, 0)} % du pipe classé`}
          </div>
        </Clickable>
        <HintLine>Cliquez une famille pour son poids et son taux de réussite</HintLine>
        <Bars
          rows={mixFamilies.map((f) => ({
            name: f.label,
            sub: `${formatNumber(f.nb)} opportunités · ${formatPct(f.part_montant_pct, 0)} % du pipe qualifié · réussite ${formatPct(f.win_rate_pct, 0)} %`,
            value: `${formatMFcfa(f.montant_xof)} M`,
            pct: topFamilyMontant ? (f.montant_xof / topFamilyMontant) * 100 : 0,
            variant: f.part_montant_pct > 40 ? ("w" as const) : undefined,
            detail: {
              kicker: "Famille d'offre · pipeline ouvert",
              title: f.label,
              tag: `${formatPct(f.part_montant_pct, 0)} % du pipe qualifié`,
              tagVariant: f.part_montant_pct > 40 ? ("w" as const) : ("a" as const),
              body: [
                `${f.label} représente ${formatMFcfa(f.montant_xof)} M FCFA sur ${formatNumber(f.nb)} opportunités ouvertes, soit ${formatPct(f.part_montant_pct, 0)} % du pipe qualifié en montant et ${formatPct(f.part_nb_pct, 0)} % en nombre. Pondéré par la probabilité déclarée, cela ressort à ${formatMFcfa(f.montant_pondere_xof)} M FCFA.`,
                f.nb_closes > 0
                  ? `Sur les ${formatNumber(f.nb_closes)} affaires déjà closes de cette famille, ${formatPct(f.win_rate_pct, 0)} % de la valeur engagée a été gagnée. Un écart entre le poids dans le pipe et le taux de réussite est le signal à lire : beaucoup se positionner là où l'on gagne peu déplace le résultat.`
                  : "Aucune affaire close sur cette famille : le taux de réussite n'est pas encore calculable.",
                `L'écart entre la part en montant (${formatPct(f.part_montant_pct, 0)} %) et la part en nombre (${formatPct(f.part_nb_pct, 0)} %) dit la taille moyenne des affaires : au-dessus, la famille se joue sur peu de gros deals ; en dessous, sur du volume.`,
              ],
              kv: [
                ["Montant du pipe", `${formatMFcfa(f.montant_xof)} M FCFA`],
                ["Montant pondéré", `${formatMFcfa(f.montant_pondere_xof)} M FCFA`],
                ["Opportunités", formatNumber(f.nb)],
                ["Part en montant", `${formatPct(f.part_montant_pct, 0)} %`],
                ["Part en nombre", `${formatPct(f.part_nb_pct, 0)} %`],
                ["Taux de réussite", f.nb_closes > 0 ? `${formatPct(f.win_rate_pct, 0)} %` : "—"],
                ["Affaires closes", formatNumber(f.nb_closes)],
              ],
              // note: "Famille déduite du libellé de l'opportunité — Odoo ne porte pas de catégorie sur crm.lead. Les parts portent sur le pipe qualifié, pas sur le pipe total.",
            },
          }))}
        />
        <Note style={{ marginTop: 14 }}>
          Famille déduite du libellé de l&apos;opportunité : {formatNumber(offerMix.coverage.nb_non_classe)}{" "}
          opportunités ({formatMFcfa(offerMix.coverage.montant_non_classe_xof)} M FCFA) portent un libellé qui ne
          dit pas ce qui est vendu — les parts ci-dessus portent donc sur {formatPct(couvertureMontant, 0)} % du
          pipe en montant.
        </Note>
      </Tile>

      {periodesAffichees.length > 0 && (
        <Tile
          span={6}
          fill
          title="Mix d'atterrissage par trimestre d'échéance"
          kick={offerMix.historique_reel ? "évolution mesurée" : "projection · non historisée"}
          aide="Comment se répartissent vos offres sur les trimestres à venir, selon les dates annoncées. Sert à repérer un trimestre qui reposerait sur une seule offre."
        >
          <HintLine>Cliquez un trimestre pour la répartition de son échéance</HintLine>
          {/* Repli calé sur le NOMBRE DE FAMILLES de la tuile de gauche, et non
              sur un seuil fixe : les deux listes ont alors autant de lignes, donc
              les deux tuiles la même hauteur. Les trimestres sont plus nombreux
              que les familles (huit contre quatre ici) et débordaient seuls. */}
          <Bars
            replierApres={mixFamilies.length}
            nom="trimestres"
            rows={periodesAffichees.map((p) => {
              const maxMontant = Math.max(...periodesAffichees.map((q) => q.montant_total_xof), 1);
              const repartition = p.families
                .filter((f) => f.montant_xof > 0)
                .map((f) => `${f.label} ${formatPct(f.part_montant_pct, 0)} %`)
                .join(" · ");
              return {
                name: p.courant ? `${p.period} (en cours)` : p.period,
                sub: `${formatNumber(p.nb_total)} opportunités${p.echu ? " · échéance dépassée" : ""}${repartition ? ` · ${repartition}` : ""}`,
                value: `${formatMFcfa(p.montant_total_xof)} M`,
                pct: (p.montant_total_xof / maxMontant) * 100,
                variant: p.echu ? ("r" as const) : undefined,
                detail: {
                  kicker: p.echu ? "Trimestre · échéance dépassée" : "Trimestre · échéance à venir",
                  title: `Échéances ${p.period}`,
                  tag: p.echu ? "à requalifier" : `${formatMFcfa(p.montant_total_xof)} M FCFA`,
                  tagVariant: p.echu ? ("r" as const) : ("a" as const),
                  body: [
                    `${formatNumber(p.nb_total)} opportunités qualifiées portent une échéance sur ${p.period}, pour ${formatMFcfa(p.montant_total_xof)} M FCFA.`,
                    p.echu
                      ? "Cette échéance est déjà passée alors que les affaires sont toujours ouvertes. Ce montant n'est pas un atterrissage à venir : c'est un stock à requalifier, et il gonfle mécaniquement la lecture des trimestres passés."
                      : "Ces affaires sont encore devant, leur mix indique la composition attendue de l'atterrissage — sous réserve que les échéances déclarées soient tenues.",
                    ...p.families
                      .filter((f) => f.montant_xof > 0)
                      .map(
                        (f) =>
                          `${f.label} : ${formatMFcfa(f.montant_xof)} M FCFA sur ${formatNumber(f.nb)} opportunités, ${formatPct(f.part_montant_pct, 0)} % du trimestre.`,
                      ),
                  ],
                  kv: [
                    ["Montant du trimestre", `${formatMFcfa(p.montant_total_xof)} M FCFA`],
                    ["Opportunités", formatNumber(p.nb_total)],
                    ["Statut", p.echu ? "échéance dépassée" : p.courant ? "trimestre en cours" : "à venir"],
                    ...p.families
                      .filter((f) => f.montant_xof > 0)
                      .map(
                        (f) =>
                          [f.label, `${formatMFcfa(f.montant_xof)} M (${formatPct(f.part_montant_pct, 0)} %)`] as [
                            string,
                            string,
                          ],
                      ),
                  ],
                  // note: "Ventilation par date de clôture prévue dans Odoo. La date de création du miroir est inexploitable (import en masse), d'où l'axe sur l'échéance.",
                },
              };
            })}
          />
          <Note style={{ marginTop: 14 }}>
            Répartition par date de clôture <em>prévue</em>, pas par évolution mesurée : le pipe ouvert
            d&apos;aujourd&apos;hui est ventilé sur ses échéances déclarées.{" "}
            {partEchu > 50
              ? `${formatPct(partEchu, 0)} % du montant qualifié (${formatNumber(offerMix.echu.nb)} opportunités) porte une échéance déjà dépassée — ces trimestres se lisent comme un stock à requalifier, pas comme un atterrissage.`
              : `${formatPct(partEchu, 0)} % du montant qualifié porte une échéance déjà dépassée.`}{" "}
            {offerMix.sans_echeance.nb > 0 &&
              `${formatNumber(offerMix.sans_echeance.nb)} opportunités sans échéance renseignée (${formatMFcfa(offerMix.sans_echeance.montant_xof)} M FCFA) n'apparaissent dans aucun trimestre.`}
          </Note>
        </Tile>
      )}
    </>
  );
}
