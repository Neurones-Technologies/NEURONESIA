import { getTresoreriePrevisionnelle, CreanceSurveillee } from "@/lib/api/daf";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bento, HintLine, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Note, Tag } from "@/components/ui/primitives";
import { ChartNote, LineChart } from "@/components/ui/chart";
import { SERIE_1 } from "@/components/ui/chart-palette";
import { SourceNote, sourceKick } from "../dc/source";
import { ExerciceNav } from "./exercice-nav";

/** Montant en millions, avec un plancher lisible.
 *
 * Le miroir porte des créances de quelques centaines de milliers de francs :
 * arrondies au million, elles s'affichaient « 0 M », ce qui se lit comme une
 * ligne cassée alors que la créance existe. */
function montantM(xof: number): string {
  if (xof > 0 && xof < 1_000_000) return "< 1 M";
  return `${formatMFcfa(xof)} M`;
}

/** Fiche de détail d'une créance, commune aux deux listes.
 *
 * Le `mode` ne change pas les données affichées mais l'ACTION qu'elles appellent :
 * relance préventive avant l'échéance, recouvrement après. */
function ligneCreance(l: CreanceSurveillee, mode: "a_echoir" | "echue") {
  const gravite = mode === "echue" && l.jours_de_retard > 90;
  return {
    kicker: mode === "a_echoir" ? "Créance à échoir · relance préventive" : "Créance échue · recouvrement",
    title: l.client,
    tag:
      mode === "a_echoir"
        ? `échoit dans ${formatNumber(l.jours_avant_echeance)} j`
        : `${formatNumber(l.jours_de_retard)} j de retard`,
    tagVariant: (gravite ? "r" : l.risque_glissement ? "w" : "n") as "r" | "w" | "n",
    body: [
      `${l.reference} — ${formatMFcfa(l.reste_du_xof)} M FCFA restant dus, échéance au ${formatDate(l.echeance)}.`,
      l.comportement_significatif
        ? `Ce client règle habituellement avec ${formatPct(l.retard_habituel_client_jours, 0)} jours de retard, mesurés sur ${formatNumber(l.nb_factures_reglees_client)} factures déjà réglées : l'encaissement est donc attendu autour du ${formatDate(l.encaissement_attendu_le)}.`
        : `Ce client n'a que ${formatNumber(l.nb_factures_reglees_client)} facture(s) réglée(s) : son comportement de paiement n'est pas encore mesurable, et le retard global constaté est utilisé par défaut pour situer l'encaissement.`,
      mode === "a_echoir"
        ? l.risque_glissement
          ? "Cette créance n'est pas encore en retard : c'est exactement le moment où un appel change la date de règlement. Le retard habituel du client rend le glissement probable."
          : "Créance à échoir sans signal particulier : la relance de courtoisie suffit."
        : gravite
          ? "Au-delà de 90 jours, la relance commerciale simple a généralement déjà échoué : l'escalade se décide."
          : "Retard récent : une relance ferme débloque habituellement le règlement.",
    ],
    kv: [
      ["Facture", l.reference],
      ["Restant dû", `${formatMFcfa(l.reste_du_xof)} M FCFA`],
      ["Montant facturé", `${formatMFcfa(l.montant_xof)} M FCFA`],
      ["Échéance", formatDate(l.echeance)],
      mode === "a_echoir"
        ? ["Jours avant échéance", formatNumber(l.jours_avant_echeance)]
        : ["Jours de retard", formatNumber(l.jours_de_retard)],
      ["Encaissement attendu", formatDate(l.encaissement_attendu_le)],
      [
        "Retard habituel du client",
        l.retard_habituel_client_jours !== null
          ? `${formatPct(l.retard_habituel_client_jours, 0)} j`
          : "non mesurable",
      ],
      ["Devise", l.devise],
    ],
  };
}

/** Tableau de bord n°3 du DAF — Trésorerie prévisionnelle.
 *
 * « Vigilance sur les créances proches de leur échéance (alerte avant échéance).
 * Prédiction des atterrissages mensuels, sur une vue calendaire, avec prévision
 * des encaissements et des décaissements mois par mois. »
 *
 * La vue calendaire est prise au mot : une grille de mois (cf. `.daf-cal` dans
 * globals.css), pas un tableau de lignes. Chaque case affiche les quatre montants
 * séparément — encaissement et décaissement, constatés et prévus — parce que
 * fondre le mesuré et le projeté dans deux colonnes ferait disparaître la seule
 * information qui compte pour décider : sait-on, ou suppose-t-on ?
 *
 * Deux avertissements structurels sont portés à l'écran, et non relégués en note
 * de bas de page :
 * - le cumul est une VARIATION de trésorerie, pas un solde bancaire (aucun compte
 *   n'est raccordé au système) ;
 * - l'arriéré (les créances attendues avant le mois en cours) est sorti du
 *   calendrier. Le laisser dedans promettait 10,8 milliards d'encaissement sur un
 *   seul mois, ce qui rendait le plan inutilisable.
 */
export async function DfTresorerie({ annee }: { annee?: number }) {
  const data = await getTresoreriePrevisionnelle(annee);

  if (!data) {
    return (
      <Bento>
        <Tile span={12} title="Trésorerie prévisionnelle">
          <Note style={{ marginTop: 0 }}>
            La trésorerie prévisionnelle n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { vigilance, atterrissage, position } = data;
  const arriere = atterrissage.arriere;
  const aVenir = atterrissage.mois.filter((m) => m.statut !== "revolu");
  const soldeAVenir = atterrissage.totaux.solde_prevu_restant_xof;

  return (
    <>
      <ExerciceNav basePath="/df/vision/tresorerie" annee={data.annee} annees={data.annees_disponibles} />

      <div className="kpi-row">
        <StatTile
          span={3}
          label={`À échoir sous ${formatNumber(vigilance.horizon_jours)} jours`}
          value={formatMFcfa(vigilance.totaux.montant_a_echoir_xof)}
          unit="M FCFA"
          reading={`${formatNumber(vigilance.totaux.nb_a_echoir)} créances · ${formatNumber(vigilance.totaux.nb_a_echoir_a_risque)} à risque de glissement`}
          readingVariant={vigilance.totaux.nb_a_echoir_a_risque > 0 ? "wat" : "pos"}
          detail={{
            kicker: "Indicateur · vigilance avant échéance",
            title: "Créances proches de leur échéance",
            tag: `${formatNumber(vigilance.totaux.nb_a_echoir)} créances`,
            tagVariant: "w",
            body: [
              `${formatMFcfa(vigilance.totaux.montant_a_echoir_xof)} M FCFA arrivent à échéance dans les ${formatNumber(vigilance.horizon_jours)} prochains jours, sur ${formatNumber(vigilance.totaux.nb_a_echoir)} créances.`,
              `${formatNumber(vigilance.totaux.nb_a_echoir_a_risque)} d'entre elles (${formatMFcfa(vigilance.totaux.montant_a_echoir_a_risque_xof)} M FCFA) sont portées par des clients dont le retard habituel mesuré dépasse une semaine : c'est là que l'appel préventif a de la valeur.`,
              vigilance.methode,
            ],
            kv: [
              ["Montant à échoir", `${formatMFcfa(vigilance.totaux.montant_a_echoir_xof)} M FCFA`],
              ["Créances concernées", formatNumber(vigilance.totaux.nb_a_echoir)],
              ["Dont à risque de glissement", formatNumber(vigilance.totaux.nb_a_echoir_a_risque)],
              ["Horizon de vigilance", `${formatNumber(vigilance.horizon_jours)} jours`],
              ["Retard global constaté", `${formatPct(vigilance.totaux.retard_global_constate_jours, 1)} j`],
            ],
          }}
        />
        <StatTile
          span={3}
          label="Encaissement prévu restant"
          value={formatMFcfa(atterrissage.totaux.encaissement_prevu_restant_xof)}
          unit="M FCFA"
          reading={`sur ${formatNumber(aVenir.length)} mois · hors arriéré`}
          readingVariant="wat"
          detail={{
            kicker: "Prévision · échéancier mesuré, comportement observé",
            title: "Encaissements attendus d'ici la fin de l'horizon",
            tag: "projection",
            tagVariant: "w",
            body: [
              `${formatMFcfa(atterrissage.totaux.encaissement_prevu_restant_xof)} M FCFA sont attendus sur les ${formatNumber(aVenir.length)} mois du calendrier restant à courir.`,
              atterrissage.hypotheses[0],
              `L'arriéré (${formatMFcfa(arriere.montant_xof)} M FCFA) n'y figure pas : il est publié séparément.`,
            ],
            kv: [
              ["Encaissement prévu", `${formatMFcfa(atterrissage.totaux.encaissement_prevu_restant_xof)} M FCFA`],
              ["Décaissement prévu", `${formatMFcfa(atterrissage.totaux.decaissement_prevu_restant_xof)} M FCFA`],
              ["Solde prévu", `${formatMFcfa(soldeAVenir)} M FCFA`],
              ["Mois couverts", formatNumber(aVenir.length)],
            ],
          }}
        />
        <StatTile
          span={3}
          label="Arriéré hors calendrier"
          value={formatMFcfa(arriere.montant_xof)}
          unit="M FCFA"
          reading={`${formatPct(arriere.part_encours_pct, 0)} % de l'encours · ${formatPct(arriere.part_plus_de_2_ans_pct, 0)} % au-delà de 2 ans`}
          readingVariant="neg"
          detail={{
            kicker: "Indicateur · mesuré, hors prévision",
            title: "Créances non datables",
            tag: `${formatNumber(arriere.nb_creances)} créances`,
            tagVariant: "r",
            body: [
              `${formatMFcfa(arriere.montant_xof)} M FCFA sur ${formatNumber(arriere.nb_creances)} créances auraient déjà dû être encaissés, même en tenant compte du retard habituel de chaque client. Cela représente ${formatPct(arriere.part_encours_pct, 1)} % de l'encours client.`,
              arriere.lecture,
              `${formatMFcfa(arriere.montant_plus_de_2_ans_xof)} M FCFA dépassent deux ans d'ancienneté, soit ${formatPct(arriere.part_plus_de_2_ans_pct, 1)} % de l'arriéré.`,
            ],
            kv: [
              ["Arriéré total", `${formatMFcfa(arriere.montant_xof)} M FCFA`],
              ["Créances concernées", formatNumber(arriere.nb_creances)],
              ["Part de l'encours", `${formatPct(arriere.part_encours_pct, 1)} %`],
              ["Dont plus de 2 ans", `${formatMFcfa(arriere.montant_plus_de_2_ans_xof)} M FCFA`],
            ],
          }}
        />
        <StatTile
          span={3}
          label="Variation cumulée"
          value={formatMFcfa(atterrissage.totaux.variation_cumulee_xof)}
          unit="M FCFA"
          reading="variation, pas un solde bancaire"
          readingVariant={atterrissage.totaux.variation_cumulee_xof < 0 ? "neg" : "pos"}
          detail={{
            kicker: "Lecture · variation de trésorerie",
            title: "Cumul du calendrier d'atterrissage",
            tag: "pas une position",
            tagVariant: "w",
            body: [
              `Le cumul des soldes mensuels du calendrier ressort à ${formatMFcfa(atterrissage.totaux.variation_cumulee_xof)} M FCFA.`,
              "Aucun solde bancaire n'existe dans le système : ce cumul est une VARIATION de trésorerie sur la période, pas une position. Un cumul négatif ne signifie pas un découvert — il signifie que la période consomme plus de trésorerie qu'elle n'en apporte.",
              position.note,
            ],
            kv: [
              ["Encaissé constaté", `${formatMFcfa(atterrissage.totaux.encaissement_constate_xof)} M FCFA`],
              ["Décaissé constaté", `${formatMFcfa(atterrissage.totaux.decaissement_constate_xof)} M FCFA`],
              ["Solde prévu restant", `${formatMFcfa(soldeAVenir)} M FCFA`],
              ["Mois en alerte", formatNumber(atterrissage.totaux.nb_mois_en_alerte)],
              ["Encours facturé", `${formatMFcfa(position.encours_facture_xof)} M FCFA`],
              ["Reste à encaisser (dossiers)", `${formatMFcfa(position.reste_a_encaisser_dossiers_xof)} M FCFA`],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={12}
          title="Où va la trésorerie"
          kick={sourceKick(atterrissage.source, "variation cumulée, mois par mois")}
        >
          {/* Le calendrier ci-dessous répond à « combien ce mois-là » ; cette courbe
              répond à « où on va ». Une seule série tracée, volontairement : une
              première version superposait les encaissements du mois au cumul. Même
              unité, mais un FLUX et un STOCK ne se lisent pas sur la même échelle —
              le flux mensuel restait écrasé dans une bande plate et n'apprenait
              rien. Le détail mensuel est dans le calendrier, juste en dessous. */}
          <LineChart
            series={[
              {
                cle: "cumul",
                libelle: "Variation cumulée de trésorerie",
                couleur: SERIE_1,
                aire: true,
                etiquetteFin: `${formatMFcfa(atterrissage.totaux.variation_cumulee_xof)} M`,
                points: atterrissage.mois.map((m) => ({
                  x: m.libelle,
                  y: m.solde_cumule_xof,
                  fiable: !m.synchronisation_incomplete && m.statut !== "a_venir",
                  info: `${m.libelle_long} — cumul ${formatMFcfa(m.solde_cumule_xof)} M (solde du mois ${formatMFcfa(m.solde_xof)} M, encaissé ${formatMFcfa(m.encaissement_retenu_xof)} M, décaissé ${formatMFcfa(m.decaissement_retenu_xof)} M)${
                    m.statut === "a_venir" ? " · projeté" : m.synchronisation_incomplete ? " · synchronisation incomplète" : ""
                  }`,
                })),
              },
            ]}
            formatY={(v) => `${formatMFcfa(v)} M`}
            zeroBase={false}
          />
          <ChartNote>
            Le trait plein s&apos;arrête où la donnée est sûre : les mois en pointillé sont soit projetés,
            soit incomplètement synchronisés. Le cumul est une VARIATION — aucun solde bancaire n&apos;existe
            dans le système, un cumul négatif ne signifie donc pas un découvert.
          </ChartNote>
        </Tile>

        <Tile
          span={12}
          title="Atterrissage mensuel"
          kick={sourceKick(atterrissage.source, `${formatNumber(atterrissage.mois.length)} mois`)}
        >
          <HintLine>Cliquez un mois pour le détail de ses encaissements et décaissements</HintLine>
          <div className="daf-cal">
            {atterrissage.mois.map((m) => {
              const classe = [
                "daf-m",
                m.statut === "revolu" ? "daf-m--v" : m.statut === "en_cours" ? "daf-m--c" : "daf-m--a",
                m.alerte ? "daf-m--al" : "",
              ]
                .filter(Boolean)
                .join(" ");
              const projete = m.statut === "a_venir";
              return (
                <Clickable
                  key={m.mois}
                  as="div"
                  className={classe}
                  detail={{
                    kicker:
                      m.statut === "revolu"
                        ? "Mois révolu · constaté"
                        : m.statut === "en_cours"
                          ? "Mois en cours · constaté et attendu"
                          : "Mois à venir · projeté",
                    title: m.libelle_long,
                    tag:
                      m.statut === "revolu" ? "mesuré" : m.statut === "en_cours" ? "en cours" : "projection",
                    tagVariant: m.statut === "revolu" ? "s" : m.statut === "en_cours" ? "a" : "w",
                    body: [
                      m.statut === "revolu"
                        ? `${formatMFcfa(m.encaissement_constate_xof)} M FCFA encaissés sur ${formatNumber(m.nb_encaissements_constates)} règlement(s), et ${formatMFcfa(m.decaissement_constate_xof)} M FCFA d'achats engagés sur ${formatNumber(m.nb_achats_engages)} commande(s).`
                        : m.statut === "en_cours"
                          ? `${formatMFcfa(m.encaissement_constate_xof)} M FCFA déjà encaissés ce mois-ci, et ${formatMFcfa(m.encaissement_prevu_xof)} M FCFA encore attendus sur ${formatNumber(m.nb_creances_attendues)} créance(s). Les décaissements affichés sont les achats déjà engagés.`
                          : `${formatMFcfa(m.encaissement_prevu_xof)} M FCFA attendus sur ${formatNumber(m.nb_creances_attendues)} créance(s) dont l'échéance, décalée du retard habituel du client, tombe sur ce mois. Le décaissement est une moyenne des ${formatNumber(atterrissage.totaux.fenetre_run_rate_mois)} derniers mois d'achats.`,
                      projete
                        ? atterrissage.hypotheses[1]
                        : "Attention à la nature du décaissement : ce sont des achats ENGAGÉS (commandes), pas des règlements fournisseurs — aucune facture fournisseur n'est synchronisée.",
                      m.alerte
                        ? "Ce mois est signalé : son solde dépasse le seuil d'alerte. Sans plafond de découvert renseigné dans le système, le seuil est posé, pas contractuel."
                        : "",
                    ].filter(Boolean),
                    kv: [
                      ["Encaissement constaté", `${formatMFcfa(m.encaissement_constate_xof)} M FCFA`],
                      ["Encaissement prévu", `${formatMFcfa(m.encaissement_prevu_xof)} M FCFA`],
                      ["Décaissement constaté", `${formatMFcfa(m.decaissement_constate_xof)} M FCFA`],
                      ["Décaissement prévu", `${formatMFcfa(m.decaissement_prevu_xof)} M FCFA`],
                      ["Solde du mois", `${formatMFcfa(m.solde_xof)} M FCFA`],
                      ["Variation cumulée", `${formatMFcfa(m.solde_cumule_xof)} M FCFA`],
                      ["Provenance encaissement", m.source_encaissement === "reel" ? "mesuré" : "projeté"],
                      ["Provenance décaissement", m.source_decaissement === "reel" ? "mesuré" : "projeté"],
                    ],
                  }}
                >
                  <div className="daf-m-h">
                    <span className="daf-m-l">{m.libelle}</span>
                    <span className="daf-m-s">
                      {m.statut === "revolu" ? "révolu" : m.statut === "en_cours" ? "en cours" : "à venir"}
                    </span>
                  </div>
                  <div className="daf-m-r daf-m-in">
                    <span>encaissé</span>
                    <b>{formatMFcfa(m.encaissement_retenu_xof)} M</b>
                  </div>
                  <div className="daf-m-r daf-m-out">
                    <span>décaissé</span>
                    <b>{formatMFcfa(m.decaissement_retenu_xof)} M</b>
                  </div>
                  <div className="daf-m-sd">
                    <b className={m.solde_xof < 0 ? "neg" : "pos"}>{formatMFcfa(m.solde_xof)} M</b>
                    <span>cum. {formatMFcfa(m.solde_cumule_xof)} M</span>
                  </div>
                  <p className="daf-m-p">
                    {m.statut === "revolu"
                      ? "mesuré"
                      : m.statut === "en_cours"
                        ? "constaté + attendu"
                        : "projeté"}
                  </p>
                </Clickable>
              );
            })}
          </div>
          <Note accent style={{ marginTop: 16 }}>
            {atterrissage.note}
          </Note>
          {atterrissage.hypotheses.map((h, i) => (
            <Note key={i} style={{ marginTop: 10 }}>
              {h}
            </Note>
          ))}
        </Tile>

        <Tile
          span={6}
          title="Créances à relancer avant échéance"
          kick={`${formatNumber(vigilance.a_echoir.length)} sous ${formatNumber(vigilance.horizon_jours)} jours`}
        >
          {vigilance.a_echoir.length > 0 ? (
            <>
              <HintLine>Cliquez une créance pour le comportement de paiement du client</HintLine>
              <div style={{ overflowX: "auto" }}>
                <table className="tb">
                  <thead>
                    <tr>
                      <th>Client</th>
                      <th className="r">Restant dû</th>
                      <th>Échéance</th>
                      <th className="r">Dans</th>
                      <th>Signal</th>
                    </tr>
                  </thead>
                  <tbody>
                    {vigilance.a_echoir.map((l) => (
                      <Clickable key={l.invoice_id} as="tr" detail={ligneCreance(l, "a_echoir")}>
                        <td>{l.client}</td>
                        <td className="r mono">{montantM(l.reste_du_xof)}</td>
                        <td className="mono">{formatDate(l.echeance)}</td>
                        <td className="r mono">{formatNumber(l.jours_avant_echeance)} j</td>
                        <td>
                          {l.risque_glissement ? (
                            <Tag variant="w">glissement probable</Tag>
                          ) : (
                            <Tag variant="n">à échéance</Tag>
                          )}
                        </td>
                      </Clickable>
                    ))}
                  </tbody>
                </table>
              </div>
              <Note style={{ marginTop: 14 }}>{vigilance.note}</Note>
            </>
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucune créance n&apos;arrive à échéance dans les {formatNumber(vigilance.horizon_jours)} prochains
              jours. Les {formatNumber(vigilance.totaux.nb_echues)} créances échues relèvent du recouvrement,
              ci-contre.
            </Note>
          )}
        </Tile>

        <Tile
          span={6}
          title="Créances échues à recouvrer"
          kick={`${formatMFcfa(vigilance.totaux.montant_echu_xof)} M FCFA · ${formatNumber(vigilance.totaux.nb_contentieux)} au-delà de 90 j`}
        >
          <HintLine>Classées par montant restant dû — l&apos;arriéré ancien est traité à part</HintLine>
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>Client</th>
                  <th className="r">Restant dû</th>
                  <th>Échéance</th>
                  <th className="r">Retard</th>
                </tr>
              </thead>
              <tbody>
                {vigilance.echues.slice(0, 10).map((l) => (
                  <Clickable key={l.invoice_id} as="tr" detail={ligneCreance(l, "echue")}>
                    <td>{l.client}</td>
                    <td className="r mono">{montantM(l.reste_du_xof)}</td>
                    <td className="mono">{formatDate(l.echeance)}</td>
                    <td className="r mono">{formatNumber(l.jours_de_retard)} j</td>
                  </Clickable>
                ))}
              </tbody>
            </table>
          </div>
          <Note accent style={{ marginTop: 14 }}>
            {arriere.lecture}
          </Note>
        </Tile>

        <Tile span={12} title="Ce que cet écran mesure et ce qu'il suppose" quiet>
          <Note style={{ marginTop: 0 }}>{position.note}</Note>
          <Note style={{ marginTop: 10 }}>{vigilance.methode}</Note>
          <SourceNote source={atterrissage.source} raison={atterrissage.hypotheses[1]} />
        </Tile>
      </Bento>
    </>
  );
}
