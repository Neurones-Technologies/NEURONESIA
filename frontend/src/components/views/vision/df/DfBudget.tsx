import { getBudgetDaf } from "@/lib/api/daf";
import { getMargins } from "@/lib/api/dashboard";
import { formatMFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, HintLine, Lst, Reste, StatTile, Tile } from "@/components/ui/bento";
import { Clickable } from "@/components/ui/detail";
import { Note, Tag } from "@/components/ui/primitives";
import { ChartNote, ColumnChart, LineChart } from "@/components/ui/chart";
import { REPERE, SERIE_1, SERIE_2 } from "@/components/ui/chart-palette";
import { SourceNote, sourceKick } from "../dc/source";
import { ExerciceNav } from "./exercice-nav";
import { ScreenLede } from "@/components/ui/screen-lede";

/** Tableau de bord n°1 du DAF — Budget.
 *
 * « Performance (indicateur global). Résultat net. Marge brute réalisée à date.
 * Top 10 des plus grosses charges (Voté). Lignes budgétaires les plus consommées. »
 *
 * Cinq indicateurs de quatre natures différentes sur un même écran : c'est le
 * risque de cette page, et ce que son ordre de lecture doit désamorcer. Le
 * mesuré vient d'abord (marge brute, charges réelles), le posé est nommé (charges
 * de structure, budget voté), et le dérivé porte le mot « projection » jusque
 * dans son libellé — un résultat net présenté comme mesuré finit cité en conseil
 * d'administration.
 *
 * Deux pièges de lecture sont traités ici plutôt que laissés au lecteur :
 * - la marge brute bascule sur une lecture de flux quand l'imputation des
 *   dépenses de dossier est trop faible, et l'écran dit laquelle il affiche ;
 * - une consommation budgétaire ne se lit jamais contre 100 % mais contre la part
 *   d'exercice écoulée, sans quoi tout début d'exercice paraît vertueux.
 */
/** Dossier tel que servi par `/v1/dashboard/margins` — le tableau de bord DAF ne
 * descend pas au dossier unitaire, cette lecture vient donc de la vue `dashboard`. */
interface DossierMarge {
  ref: string;
  client: string;
  projet: string;
  ca_provisoire: number;
  ca_definitif: number;
  perc_marge_prov: number;
  perc_marge_def: number;
}

/** En deçà de ce taux, la marge n'est plus une perte d'exploitation mais un
 * artefact de solde : le miroir porte des dossiers à -2 640 % de marge, où une
 * dépense a été imputée sur un dossier dont le CA a été facturé ailleurs. Les
 * afficher chasserait les vraies pertes du classement. Le nombre de dossiers
 * écartés est publié à l'écran plutôt que masqué. */
const MARGE_PLANCHER_PCT = -100;

export async function DfBudget({ annee }: { annee?: number }) {
  // 50 est le plafond accepté par `/v1/dashboard/margins` (le=50) : au-delà,
  // l'API répond 422 et le rendu serveur de la page tombe en erreur.
  const [data, margins] = await Promise.all([getBudgetDaf(annee), getMargins(annee, 50)]);

  if (!data) {
    return (
      <Bento>
        <Tile span={12} title="Budget">
          <Note style={{ marginTop: 0 }}>
            Le tableau de bord budgétaire n&apos;est pas accessible depuis ce profil.
          </Note>
        </Tile>
      </Bento>
    );
  }

  const { performance, resultat_net: resultat, marge_brute: marge, top_charges: charges } = data;
  const lignes = data.lignes_budgetaires;
  const surFlux = marge.lecture_retenue === "flux";
  const indice = performance.indice_pct;
  const indiceFaible = indice !== null && indice < 85;
  const maxLigne = Math.max(...lignes.lignes.map((l) => l.consommation_pct), 100);

  // Dossiers dont la marge constatée est la plus basse. Le budget se lit par
  // ligne de charge ; ce classement dit sur QUELS CHANTIERS la marge s'est
  // effectivement perdue — l'information que ni le budget ni les charges ne
  // portent.
  const dossiersFactures = ((margins?.top_dossiers ?? []) as unknown as DossierMarge[]).filter(
    (d) => d.ca_definitif > 0
  );
  const dossiersMesurables = dossiersFactures.filter((d) => d.perc_marge_def > MARGE_PLANCHER_PCT);
  const nbArtefacts = dossiersFactures.length - dossiersMesurables.length;
  const margesFaibles = dossiersMesurables
    .slice()
    .sort((a, b) => a.perc_marge_def - b.perc_marge_def)
    .slice(0, 5);
  const burn = data.burn_down;
  const margeAn = data.marge_annuelle;

  return (
    <>
      <ExerciceNav basePath="/df/vision/budget" annee={data.annee} annees={data.annees_disponibles} />

      {/* Accroche composée des données déjà chargées : aucun appel de plus. Elle
          remplace le `Brief` de l'onglet Encours, qui ne peut pas être réutilisé
          ici — `getBriefing()` produit un briefing par RÔLE, donc le même texte
          sur les cinq onglets du profil. */}
      <ScreenLede
        texte={
          `L'indice de performance financière ressort à ${formatPct(indice, 0)} sur 100 — verdict « ${performance.verdict} ». ` +
          `Le résultat net projeté s'établit à ${formatMFcfa(resultat.resultat_net_projete_xof)} M FCFA, ` +
          `pour ${formatMFcfa(charges.totaux.montant_total_xof)} M FCFA de charges engagées sur l'exercice.`
        }
        signaux={[
          { label: `marge brute ${formatPct(marge.taux_retenu_pct, 1)} %`, alerte: indiceFaible },
          {
            label: (() => {
              const n = lignes.lignes.filter((l) => l.statut === "depasse").length;
              return n > 1
                ? `${formatNumber(n)} lignes budgétaires dépassées`
                : `${formatNumber(n)} ligne budgétaire dépassée`;
            })(),
            alerte: lignes.lignes.some((l) => l.statut === "depasse"),
          },
          { label: surFlux ? "marge lue sur les flux" : "marge lue par dossier" },
          { label: `${formatNumber(charges.totaux.nb_fournisseurs)} fournisseurs` },
        ]}
      />

      <div className="kpi-row">
        {/* L'indice composite est le seul chiffre de l'écran qui porte un verdict :
            c'est lui qu'on vient chercher, les trois autres l'expliquent. */}
        <StatTile
          span={3}
          rang="principal"
          label="Performance"
          aide="Une note d'ensemble de la santé financière, qui résume plusieurs indicateurs en un seul chiffre. Le détail de sa composition est juste en dessous."
          value={indice !== null ? formatPct(indice, 0) : "—"}
          unit="/ 100"
          reading={performance.verdict}
          readingVariant={indiceFaible ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur global · composite",
            title: "Indice de performance financière",
            tag: performance.verdict,
            tagVariant: indiceFaible ? "r" : "s",
            body: [
              `L'indice ressort à ${formatPct(indice, 1)} sur 100, verdict « ${performance.verdict} ». Il agrège ${formatNumber(performance.composantes.length)} composantes mesurées, chacune rapportée à une cible posée.`,
              performance.regle,
              performance.note,
            ],
            kv: performance.composantes.map((c) => [
              `${c.libelle} (${formatNumber(c.poids_pct)} %)`,
              c.taux_atteinte_pct !== null
                ? `${formatPct(c.valeur, 1)} ${c.unite} → ${formatPct(c.taux_atteinte_pct, 0)} % de la cible`
                : "non mesurable",
            ]),
          }}
        />
        <StatTile
          span={3}
          label="Marge brute réalisée"
          aide="Ce qui reste une fois retiré le coût direct de ce que vous avez vendu. C'est un chiffre constaté, pas une prévision."
          value={formatPct(marge.taux_retenu_pct, 1)}
          unit="%"
          reading={
            surFlux
              ? `${formatMFcfa(marge.marge_retenue_xof)} M · lecture de flux`
              : `${formatMFcfa(marge.marge_retenue_xof)} M sur ${formatNumber(marge.couverture.nb_dossiers_imputes)} dossiers`
          }
          readingVariant={surFlux ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · marge mesurée",
            title: "Marge brute réalisée à date",
            tag: surFlux ? "lecture de flux" : "par dossier",
            tagVariant: surFlux ? "w" : "s",
            body: [
              surFlux
                ? `L'imputation des dépenses de dossier ne couvre que ${formatPct(marge.couverture.couverture_pct, 1)} % du CA de l'exercice : la marge affichée est donc calculée sur les flux — ${formatMFcfa(marge.lecture_flux.ca_signe_xof)} M FCFA signés moins ${formatMFcfa(marge.lecture_flux.achats_engages_xof)} M FCFA d'achats engagés.`
                : `${formatMFcfa(marge.marge_xof)} M FCFA de marge sur ${formatMFcfa(marge.ca_realise_xof)} M FCFA de CA définitif, mesurés sur ${formatNumber(marge.couverture.nb_dossiers_imputes)} dossiers dont la dépense est imputée.`,
              marge.couverture.raison_non_exploitable || marge.lecture_flux.limites,
              marge.note,
            ],
            kv: [
              ["Lecture affichée", surFlux ? "flux engagés" : "par dossier"],
              ["Marge par dossier", `${formatPct(marge.taux_pct, 1)} %`],
              ["Marge sur flux", `${formatPct(marge.lecture_flux.taux_pct, 1)} %`],
              ["Couverture de l'imputation", `${formatPct(marge.couverture.couverture_pct, 1)} %`],
              ["Cible", `${formatPct(marge.cible_taux_pct, 0)} %`],
            ],
          }}
        />
        <StatTile
          span={3}
          label="Résultat net projeté"
          aide="Ce que l'exercice devrait laisser en fin d'année, une fois toutes les charges déduites. C'est une projection : elle repose sur des hypothèses de charges, pas sur des factures reçues."
          value={formatMFcfa(resultat.resultat_net_projete_xof)}
          unit="M FCFA"
          reading={`projection · ${formatNumber(resultat.mois_ecoules)} mois de charges`}
          readingVariant={resultat.resultat_net_projete_xof < 0 ? "neg" : "wat"}
          detail={{
            kicker: "Projection · non mesuré",
            title: "Résultat net projeté",
            tag: "projection",
            tagVariant: "w",
            body: [
              `Marge brute mesurée de ${formatMFcfa(resultat.marge_brute_xof)} M FCFA, moins ${formatMFcfa(resultat.charges_structure_xof)} M FCFA de charges de structure posées sur ${formatNumber(resultat.mois_ecoules)} mois, moins ${formatMFcfa(resultat.impot_xof)} M FCFA d'impôt au taux de ${formatPct(resultat.taux_is_pct, 0)} %.`,
              resultat.raison,
              resultat.note,
            ],
            kv: [
              ["Marge brute (mesurée)", `${formatMFcfa(resultat.marge_brute_xof)} M FCFA`],
              ["Charges de structure (posées)", `${formatMFcfa(resultat.charges_structure_xof)} M FCFA`],
              ["Résultat avant impôt", `${formatMFcfa(resultat.resultat_avant_impot_xof)} M FCFA`],
              ["Impôt projeté", `${formatMFcfa(resultat.impot_xof)} M FCFA`],
              ["Résultat net projeté", `${formatMFcfa(resultat.resultat_net_projete_xof)} M FCFA`],
            ],
          }}
        />
        {/* Assiette de calcul, pas un verdict : le total engagé sert à lire les
            trois autres indicateurs, il ne se lit pas seul. */}
        <StatTile
          span={3}
          rang="contexte"
          label="Charges engagées"
          aide="Ce que vous avez commandé à vos fournisseurs depuis le début de l'exercice. Engagé ne veut pas dire payé : la dépense est décidée, le règlement peut venir plus tard."
          value={formatMFcfa(charges.totaux.montant_total_xof)}
          unit="M FCFA"
          reading={
            charges.totaux.variation_pct !== null
              ? `${charges.totaux.variation_pct > 0 ? "+" : ""}${formatPct(charges.totaux.variation_pct, 0)} % vs ${data.annee - 1}`
              : `${formatNumber(charges.totaux.nb_commandes)} commandes`
          }
          readingVariant={(charges.totaux.variation_pct ?? 0) > 0 ? "neg" : "pos"}
          detail={{
            kicker: "Indicateur · achats mesurés",
            title: "Charges fournisseurs engagées",
            tag: `${formatNumber(charges.totaux.nb_fournisseurs)} fournisseurs`,
            tagVariant: "s",
            body: [
              `${formatMFcfa(charges.totaux.montant_total_xof)} M FCFA engagés sur ${formatNumber(charges.totaux.nb_commandes)} commandes d'achat en ${data.annee}, auprès de ${formatNumber(charges.totaux.nb_fournisseurs)} fournisseurs.`,
              charges.perimetre,
              charges.note,
            ],
            kv: [
              ["Engagé cet exercice", `${formatMFcfa(charges.totaux.montant_total_xof)} M FCFA`],
              ["Engagé exercice précédent", `${formatMFcfa(charges.totaux.montant_exercice_precedent_xof)} M FCFA`],
              ["Part du top affiché", `${formatPct(charges.totaux.part_top_pct, 0)} %`],
              ["Commandes en devise", formatNumber(charges.totaux.nb_commandes_en_devise)],
            ],
          }}
        />
      </div>

      <Bento>
        <Tile
          span={7}
          title="De quoi l'indice de performance est fait"
          kick={sourceKick(performance.source, `${formatNumber(performance.poids_retenu_pct)} % du poids retenu`)}
          aide="Le détail de la note ci-dessus : quels éléments y entrent et combien chacun pèse. Permet de contester le calcul, pas seulement le résultat."
        >
          <HintLine>Cliquez une composante pour sa mesure et sa cible</HintLine>
          <Bars
            rows={performance.composantes.map((c) => {
              const atteinte = c.taux_atteinte_pct;
              const faible = atteinte !== null && atteinte < 70;
              return {
                name: `${c.libelle} · ${formatNumber(c.poids_pct)} %`,
                sub:
                  atteinte !== null
                    ? `${formatPct(c.valeur, 1)} ${c.unite} pour une cible de ${formatPct(c.cible, c.unite === "jours" ? 0 : 1)} ${c.unite}`
                    : "non mesurable sur cet exercice — écartée de l'indice",
                value: atteinte !== null ? `${formatPct(atteinte, 0)} %` : "—",
                pct: atteinte ?? 0,
                variant: atteinte === null ? undefined : faible ? ("r" as const) : atteinte >= 100 ? ("s" as const) : ("w" as const),
                detail: {
                  kicker: "Composante de l'indice",
                  title: c.libelle,
                  tag: atteinte !== null ? `${formatPct(atteinte, 0)} % de la cible` : "non mesurable",
                  tagVariant: atteinte === null ? "n" : faible ? "r" : atteinte >= 100 ? "s" : "w",
                  body: [
                    `Mesure : ${c.mesure}.`,
                    atteinte !== null
                      ? `Valeur constatée ${formatPct(c.valeur, 1)} ${c.unite}, cible ${formatPct(c.cible, c.unite === "jours" ? 0 : 1)} ${c.unite} — ${c.sens === "bas" ? "l'indicateur est meilleur quand il baisse" : "l'indicateur est meilleur quand il monte"}.`
                      : "Cette composante est écartée de l'indice faute de mesure exploitable : la remplacer par une valeur neutre aurait flatté ou effondré l'indice sans raison.",
                    c.commentaire,
                  ],
                  kv: [
                    ["Poids dans l'indice", `${formatNumber(c.poids_pct)} %`],
                    ["Valeur mesurée", c.valeur !== null ? `${formatPct(c.valeur, 1)} ${c.unite}` : "—"],
                    ["Cible posée", `${formatPct(c.cible, c.unite === "jours" ? 0 : 1)} ${c.unite}`],
                    ["Taux d'atteinte", atteinte !== null ? `${formatPct(atteinte, 0)} %` : "—"],
                    ["Provenance", c.source === "reel" ? "mesurée" : "cible posée"],
                  ],
                },
              };
            })}
          />
          <SourceNote source={performance.source} raison={performance.regle} avertissement={performance.avertissement} />
        </Tile>

        <Tile
          span={5}
          title="Charges de structure retenues dans la projection"
          kick={sourceKick("statique")}
          aide="Les dépenses fixes supposées pour l'année : loyers, salaires, abonnements. Elles ne sont pas lues dans la comptabilité mais posées à la main — les changer change le résultat projeté."
        >
          <Bars
            rows={resultat.charges_detail.slice(0, 6).map((c) => ({
              name: c.poste,
              sub: `${c.nature === "fixe" ? "charge fixe" : "charge variable"} · ${formatMFcfa(c.montant_periode_xof)} M sur ${formatNumber(resultat.mois_ecoules)} mois`,
              value: `${formatMFcfa(c.montant_mensuel_xof)} M/mois`,
              pct: c.part_pct,
              variant: "w" as const,
              detail: {
                kicker: "Poste de charge · posé",
                title: c.poste,
                tag: c.nature === "fixe" ? "fixe" : "variable",
                tagVariant: "w",
                body: [
                  `${formatMFcfa(c.montant_mensuel_xof)} M FCFA par mois, soit ${formatMFcfa(c.montant_periode_xof)} M FCFA sur les ${formatNumber(resultat.mois_ecoules)} mois écoulés de l'exercice — ${formatPct(c.part_pct, 1)} % des charges de structure retenues.`,
                  resultat.raison,
                ],
                kv: [
                  ["Montant mensuel", `${formatMFcfa(c.montant_mensuel_xof)} M FCFA`],
                  ["Cumul à date", `${formatMFcfa(c.montant_periode_xof)} M FCFA`],
                  ["Part des charges", `${formatPct(c.part_pct, 1)} %`],
                  ["Nature", c.nature === "fixe" ? "fixe" : "variable"],
                ],
              },
            }))}
          />
          <SourceNote source={resultat.source} raison={resultat.raison} avertissement={resultat.avertissement} />
        </Tile>

        <Tile
          span={7}
          title="Consommation d'achats contre rythme budgétaire"
          kick={sourceKick(burn.source, `${formatNumber(burn.resume.mois_couverts)} mois cumulés`)}
          aide="Votre rythme de dépense comparé à celui qui permettrait de tenir l'année. Au-dessus de la ligne, le budget s'épuise trop vite."
        >
          <LineChart
            series={[
              {
                cle: "ca",
                libelle: "CA signé cumulé",
                couleur: SERIE_2,
                etiquetteFin: `${formatMFcfa(burn.resume.ca_cumule_xof)} M`,
                points: burn.points.map((p) => ({
                  x: p.libelle,
                  y: p.ca_cumule_xof,
                  info: `${p.libelle} — CA cumulé ${formatMFcfa(p.ca_cumule_xof)} M (${formatMFcfa(p.ca_mois_xof)} M sur le mois)`,
                })),
              },
              {
                cle: "achats",
                libelle: "Achats engagés cumulés",
                couleur: SERIE_1,
                etiquetteFin: `${formatMFcfa(burn.resume.achats_cumules_xof)} M`,
                points: burn.points.map((p) => ({
                  x: p.libelle,
                  y: p.achats_cumules_xof,
                  info: `${p.libelle} — achats cumulés ${formatMFcfa(p.achats_cumules_xof)} M (${formatMFcfa(p.achats_mois_xof)} M sur le mois)`,
                })),
              },
              {
                cle: "rythme",
                libelle: "Rythme du budget posé",
                couleur: REPERE,
                repere: true,
                points: burn.points.map((p) => ({
                  x: p.libelle,
                  y: p.rythme_budget_xof,
                  info: `${p.libelle} — rythme théorique ${formatMFcfa(p.rythme_budget_xof)} M`,
                })),
              },
            ]}
            formatY={(v) => `${formatMFcfa(v)} M`}
          />
          <ChartNote>
            Achats en retrait de {formatMFcfa(Math.abs(burn.resume.ecart_rythme_xof))} M sur le rythme, mais le
            CA signé cumulé atteint {formatMFcfa(burn.resume.ca_cumule_xof)} M — la marge de flux tient à{" "}
            {formatPct(burn.resume.taux_marge_flux_pct, 1)} %. La sous-consommation n&apos;est donc pas une
            baisse d&apos;activité.
          </ChartNote>
          <SourceNote source={burn.source} raison={burn.raison} avertissement={burn.avertissement} />
        </Tile>

        <Tile
          span={5}
          title="Taux de marge par exercice"
          kick={`${formatNumber(margeAn.resume.nb_exploitables)} exercices comparables`}
          aide="L'évolution de votre marge d'une année sur l'autre. Seuls les exercices suffisamment documentés sont comparés — les autres donneraient une fausse tendance."
        >
          {/* Seuls les exercices comparables sont tracés. L'exercice en cours
              afficherait 96,7 % de marge sur deux dossiers imputés : la colonne
              écrasait l'échelle et faisait paraître les exercices mesurés plats.
              Il reste nommé sous le graphe, avec la raison de son absence. */}
          <ColumnChart
            colonnes={margeAn.points
              .filter((p) => p.exploitable)
              .map((p) => ({
                x: p.libelle,
                y: p.taux_pct,
                etiquette: `${formatPct(p.taux_pct, 0)}`,
                info: `${p.annee} — marge ${formatPct(p.taux_pct, 1)} % sur ${formatMFcfa(p.ca_impute_xof)} M de CA imputé (${formatNumber(p.nb_imputes)} dossiers sur ${formatNumber(p.nb_dossiers)}, couverture ${formatPct(p.couverture_pct, 0)} %)`,
              }))}
            formatY={(v) => `${Math.round(v)} %`}
            couleur={SERIE_1}
            reference={{ valeur: margeAn.cible_pct, libelle: `cible ${formatPct(margeAn.cible_pct, 0)} %` }}
          />
          <ChartNote>
            {margeAn.points
              .filter((p) => !p.exploitable)
              .map(
                (p) =>
                  `${p.annee} n'est pas tracé : ${formatNumber(p.nb_imputes)} dossiers sur ${formatNumber(p.nb_dossiers)} portent une dépense imputée (${formatPct(p.couverture_pct, 1)} % du CA), trop peu pour se comparer aux exercices voisins.`,
              )
              .join(" ")}{" "}
            Dernier exercice pleinement mesuré : {margeAn.resume.dernier_exercice_exploitable ?? "—"}.
          </ChartNote>
        </Tile>

        <Tile
          span={12}
          title="Top des plus grosses charges"
          kick={`${formatNumber(charges.charges.length)} fournisseurs · voté`}
          aide="Vos plus gros postes de dépense, par fournisseur. C'est là que quelques renégociations pèsent le plus."
        >
          <HintLine>Cliquez une ligne pour son détail et son rattachement budgétaire</HintLine>
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Fournisseur</th>
                  <th className="r">Engagé</th>
                  <th className="r">Part</th>
                  <th className="r">Cumul</th>
                  <th>Ligne budgétaire</th>
                </tr>
              </thead>
              <tbody>
                {charges.charges.map((c) => (
                  <Clickable
                    key={c.rang}
                    as="tr"
                    detail={{
                      kicker: "Charge fournisseur · mesurée",
                      title: c.fournisseur,
                      tag: `${formatPct(c.part_pct, 1)} % des achats`,
                      tagVariant: c.part_pct > 15 ? "r" : "w",
                      body: [
                        `${formatMFcfa(c.montant_xof)} M FCFA engagés sur ${formatNumber(c.nb_commandes)} commande(s) en ${data.annee}, soit un montant moyen de ${formatMFcfa(c.montant_moyen_xof)} M FCFA par commande.`,
                        `Ce fournisseur pèse ${formatPct(c.part_pct, 1)} % des achats de l'exercice ; les ${formatNumber(c.rang)} premiers en cumulent ${formatPct(c.part_cumulee_pct, 1)} %.`,
                        c.devises.some((d) => d !== "XOF")
                          ? `Commandes libellées en ${c.devises.join(", ")} : le montant est converti par l'ERP, le taux appliqué n'est pas conservé dans le miroir.`
                          : charges.perimetre,
                      ],
                      kv: [
                        ["Montant engagé", `${formatMFcfa(c.montant_xof)} M FCFA`],
                        ["Commandes", formatNumber(c.nb_commandes)],
                        ["Montant moyen", `${formatMFcfa(c.montant_moyen_xof)} M FCFA`],
                        ["Part des achats", `${formatPct(c.part_pct, 1)} %`],
                        ["Dernière commande", c.derniere_commande ?? "—"],
                        ["Ligne budgétaire", c.ligne_budgetaire],
                        ["Devises", c.devises.join(", ")],
                      ],
                    }}
                  >
                    <td className="mono">{c.rang}</td>
                    <td>{c.fournisseur}</td>
                    <td className="r mono">{formatMFcfa(c.montant_xof)} M</td>
                    <td className="r mono">{formatPct(c.part_pct, 1)} %</td>
                    <td className="r mono">{formatPct(c.part_cumulee_pct, 1)} %</td>
                    <td>
                      <Tag variant={c.ligne_budgetaire.startsWith("Frais généraux") ? "w" : "n"}>
                        {c.ligne_budgetaire}
                      </Tag>
                    </td>
                  </Clickable>
                ))}
              </tbody>
            </table>
          </div>
          {/* Pareto : part de chaque fournisseur ET cumul, tous deux en % du total
              des achats. Exprimer les deux dans la même unité évite le second axe
              — deux échelles superposées inventent une corrélation absente. */}
          <ColumnChart
            colonnes={charges.charges.map((c) => ({
              x: `${c.rang}`,
              y: c.part_pct,
              etiquette: c.part_pct >= 5 ? `${formatPct(c.part_pct, 0)}` : undefined,
              info: `${c.rang}. ${c.fournisseur} — ${formatMFcfa(c.montant_xof)} M, soit ${formatPct(c.part_pct, 1)} % des achats (cumul ${formatPct(c.part_cumulee_pct, 1)} %)`,
            }))}
            cumul={charges.charges.map((c) => c.part_cumulee_pct)}
            couleur={SERIE_1}
            couleurCumul={REPERE}
            formatY={(v) => `${Math.round(v)} %`}
            libelleColonnes="Part des achats de l'exercice"
            libelleCumul="Part cumulée"
            hauteur={200}
          />
          <ChartNote>
            Les {formatNumber(Math.min(5, charges.charges.length))} premiers fournisseurs concentrent{" "}
            {formatPct(charges.charges[4]?.part_cumulee_pct ?? charges.totaux.part_top_pct, 0)} % des achats sur{" "}
            {formatNumber(charges.totaux.nb_fournisseurs)} au total. Le coude de la courbe marque la frontière
            entre ce qui se négocie fournisseur par fournisseur et ce qui se gère par catégorie.
          </ChartNote>
          <Note accent style={{ marginTop: 14 }}>
            {charges.perimetre}
          </Note>
        </Tile>

        <Tile
          span={7}
          title="Lignes budgétaires les plus consommées"
          aide="Les postes du budget qui s'épuisent le plus vite, rapportés à ce qui était prévu. Sert à repérer un dépassement avant la fin de l'exercice."
          kick={sourceKick(
            lignes.source,
            lignes.totaux.part_exercice_ecoulee_pct !== null
              ? `exercice écoulé à ${formatPct(lignes.totaux.part_exercice_ecoulee_pct, 0)} %`
              : "exercice révolu",
          )}
        >
          <HintLine>Cliquez une ligne pour son rythme et ses principaux fournisseurs</HintLine>
          <Bars
            rows={lignes.lignes.map((l) => {
              const enAvance = l.ecart_rythme_pts > 0;
              return {
                name: l.ligne,
                sub: [
                  `budget ${formatMFcfa(l.budget_annuel_xof)} M`,
                  `consommé ${formatMFcfa(l.consomme_xof)} M`,
                  `${enAvance ? "+" : ""}${formatPct(l.ecart_rythme_pts, 0)} pts vs rythme`,
                ].join(" · "),
                value: `${formatPct(l.consommation_pct, 0)} %`,
                pct: (l.consommation_pct / maxLigne) * 100,
                variant:
                  l.statut === "depasse" ? ("r" as const) : l.statut === "tendu" ? ("w" as const) : ("s" as const),
                detail: {
                  kicker: l.ligne_de_recueil ? "Ligne de recueil · à reclasser" : "Ligne budgétaire",
                  title: l.ligne,
                  tag:
                    l.statut === "depasse"
                      ? "budget dépassé"
                      : l.statut === "tendu"
                        ? "consommation en avance"
                        : "dans le rythme",
                  tagVariant: l.statut === "depasse" ? "r" : l.statut === "tendu" ? "w" : "s",
                  body: [
                    `${formatMFcfa(l.consomme_xof)} M FCFA consommés sur un budget de ${formatMFcfa(l.budget_annuel_xof)} M FCFA, soit ${formatPct(l.consommation_pct, 1)} %, sur ${formatNumber(l.nb_commandes)} commande(s) auprès de ${formatNumber(l.nb_fournisseurs)} fournisseur(s).`,
                    l.part_exercice_ecoulee_pct !== null
                      ? `L'exercice est écoulé à ${formatPct(l.part_exercice_ecoulee_pct, 0)} % : l'écart de rythme est de ${formatPct(l.ecart_rythme_pts, 0)} points. C'est cet écart qui signale une dérive, pas le taux brut.`
                      : "L'exercice est révolu : la consommation se lit contre le budget plein.",
                    l.ligne_de_recueil
                      ? "Cette ligne n'est pas une ligne budgétaire réelle : elle recueille les achats qu'aucun motif de la grille n'a rattachés. Ce qu'elle contient est à reclasser."
                      : l.commentaire,
                  ],
                  kv: [
                    ["Budget posé", `${formatMFcfa(l.budget_annuel_xof)} M FCFA`],
                    ["Consommé (mesuré)", `${formatMFcfa(l.consomme_xof)} M FCFA`],
                    ["Reste", `${formatMFcfa(l.reste_xof)} M FCFA`],
                    ["Consommation", `${formatPct(l.consommation_pct, 1)} %`],
                    ["Écart de rythme", `${formatPct(l.ecart_rythme_pts, 0)} pts`],
                    ["Commandes", formatNumber(l.nb_commandes)],
                    ...l.top_fournisseurs.slice(0, 3).map(
                      (f) => [f.fournisseur, `${formatMFcfa(f.montant_xof)} M FCFA`] as const,
                    ),
                  ],
                },
              };
            })}
          />
          <SourceNote source={lignes.source} raison={lignes.regle_mapping} avertissement={lignes.raison} />
        </Tile>

        <Tile
          span={5}
          title={surFlux ? "Marge : les deux lectures disponibles" : "Marge réalisée mois par mois"}
          kick={surFlux ? "imputation insuffisante" : `${formatNumber(marge.couverture.nb_dossiers_imputes)} dossiers imputés`}
          aide="L'évolution de la marge au fil des mois. Elle ne peut être calculée que sur les dossiers dont les dépenses ont été rattachées : la couverture est indiquée avec le chiffre."
        >
          {surFlux ? (
            <>
              <Lst
                items={[
                  {
                    title: "Marge sur flux engagés",
                    sub: `${formatMFcfa(marge.lecture_flux.ca_signe_xof)} M signés − ${formatMFcfa(marge.lecture_flux.achats_engages_xof)} M achetés`,
                    tag: `${formatPct(marge.lecture_flux.taux_pct, 1)} %`,
                    tagVariant: "s" as const,
                    detail: {
                      kicker: "Lecture retenue · mesurée",
                      title: "Marge sur flux engagés",
                      tag: "affichée",
                      tagVariant: "s" as const,
                      body: [
                        `${formatMFcfa(marge.lecture_flux.marge_xof)} M FCFA de marge, sur ${formatNumber(marge.lecture_flux.nb_commandes_vente)} commandes de vente et ${formatNumber(marge.lecture_flux.nb_commandes_achat)} commandes d'achat.`,
                        marge.lecture_flux.limites,
                      ],
                      kv: [
                        ["CA signé", `${formatMFcfa(marge.lecture_flux.ca_signe_xof)} M FCFA`],
                        ["Achats engagés", `${formatMFcfa(marge.lecture_flux.achats_engages_xof)} M FCFA`],
                        ["Marge", `${formatMFcfa(marge.lecture_flux.marge_xof)} M FCFA`],
                        ["Taux", `${formatPct(marge.lecture_flux.taux_pct, 1)} %`],
                      ],
                    },
                  },
                  {
                    title: "Marge par dossier",
                    sub: `${formatNumber(marge.couverture.nb_dossiers_imputes)} dossiers imputés sur ${formatNumber(marge.couverture.nb_dossiers_exercice)}`,
                    tag: `${formatPct(marge.taux_pct, 1)} %`,
                    tagVariant: "r" as const,
                    detail: {
                      kicker: "Lecture écartée · couverture insuffisante",
                      title: "Marge par dossier",
                      tag: "non exploitable",
                      tagVariant: "r" as const,
                      body: [
                        `Calculée sur ${formatMFcfa(marge.ca_realise_xof)} M FCFA de CA définitif seulement, soit ${formatPct(marge.couverture.couverture_pct, 1)} % de l'exercice.`,
                        marge.couverture.raison_non_exploitable,
                      ],
                      kv: [
                        ["Dossiers de l'exercice", formatNumber(marge.couverture.nb_dossiers_exercice)],
                        ["Dossiers imputés", formatNumber(marge.couverture.nb_dossiers_imputes)],
                        ["Couverture", `${formatPct(marge.couverture.couverture_pct, 1)} %`],
                        ["Seuil d'exploitabilité", `${formatPct(marge.couverture.seuil_exploitable_pct, 0)} %`],
                      ],
                    },
                  },
                ]}
              />
              <Note accent style={{ marginTop: 14 }}>
                {marge.couverture.raison_non_exploitable}
              </Note>
            </>
          ) : (
            <Bars
              rows={marge.serie_mensuelle
                .filter((m) => m.ca_xof > 0)
                .map((m) => ({
                  name: m.libelle,
                  sub: `${formatMFcfa(m.ca_xof)} M de CA · ${formatNumber(m.nb_dossiers)} dossier(s)`,
                  value: `${formatPct(m.taux_pct, 0)} %`,
                  pct: m.taux_pct,
                  variant:
                    m.taux_pct >= marge.cible_taux_pct ? ("s" as const) : ("w" as const),
                  detail: {
                    kicker: "Marge mensuelle · mesurée",
                    title: m.libelle,
                    tag: `${formatPct(m.taux_pct, 1)} %`,
                    tagVariant: m.taux_pct >= marge.cible_taux_pct ? "s" : "w",
                    body: [
                      `${formatMFcfa(m.marge_xof)} M FCFA de marge pour ${formatMFcfa(m.ca_xof)} M FCFA de CA définitif et ${formatMFcfa(m.depense_xof)} M FCFA de dépense imputée, sur ${formatNumber(m.nb_dossiers)} dossier(s).`,
                      "Seuls les dossiers dont la dépense est imputée entrent dans cette série : un mois sans dépense imputée afficherait 100 % de marge.",
                    ],
                    kv: [
                      ["CA définitif", `${formatMFcfa(m.ca_xof)} M FCFA`],
                      ["Dépense imputée", `${formatMFcfa(m.depense_xof)} M FCFA`],
                      ["Marge", `${formatMFcfa(m.marge_xof)} M FCFA`],
                      ["Dossiers", formatNumber(m.nb_dossiers)],
                    ],
                  },
                }))}
            />
          )}
        </Tile>

        {margesFaibles.length > 0 && (
          <Tile
            span={12}
            title="Dossiers où la marge s'est perdue"
            kick={`${formatNumber(dossiersMesurables.length)} dossiers facturés · les 5 plus bas taux`}
            aide="Les chantiers dont la marge constatée est la plus faible, une fois les dépenses imputées. Le budget dit combien on dépense par nature de charge ; ce classement dit sur quels dossiers l'argent a été perdu."
          >
            <HintLine>Cliquez un dossier pour l&apos;écart entre marge prévue et constatée</HintLine>
            <Bars
              rows={margesFaibles.map((d) => {
                const perte = d.perc_marge_def < 0;
                const ecart = d.perc_marge_def - d.perc_marge_prov;
                return {
                  name: `${d.ref} · ${d.client}`,
                  sub: [
                    d.projet || "projet non renseigné",
                    `${formatMFcfa(d.ca_definitif)} M facturés`,
                    `prévue ${formatPct(d.perc_marge_prov, 0)} %`,
                  ].join(" · "),
                  value: `${formatPct(d.perc_marge_def, 1)} %`,
                  // Barre proportionnelle à la GRAVITÉ (l'écart au seuil bas), et
                  // non au taux lui-même : un taux négatif tracerait une barre
                  // négative, donc invisible.
                  pct: Math.min(100, ((MARGE_PLANCHER_PCT - d.perc_marge_def) / MARGE_PLANCHER_PCT) * 100),
                  variant: perte ? ("r" as const) : ("w" as const),
                  detail: {
                    kicker: "Dossier · marge constatée",
                    title: `${d.ref} · ${d.client}`,
                    tag: perte ? "marge négative" : "marge faible",
                    tagVariant: perte ? ("r" as const) : ("w" as const),
                    body: [
                      `Le dossier « ${d.projet || d.ref} » affiche une marge constatée de ${formatPct(d.perc_marge_def, 1)} % pour ${formatMFcfa(d.ca_definitif)} M FCFA facturés, contre ${formatPct(d.perc_marge_prov, 0)} % prévus au chiffrage — un écart de ${formatPct(ecart, 0)} points.`,
                      perte
                        ? "La marge est négative : le dossier a coûté plus qu'il n'a rapporté. À instruire avec la direction commerciale et les opérations — l'écart vient soit du chiffrage initial, soit de dépenses non refacturées."
                        : "La marge reste positive mais nettement sous le niveau attendu de l'activité. Un dossier de ce taux consomme de la capacité sans reconstituer de résultat.",
                      "La marge n'est calculable que sur les dossiers dont les dépenses sont imputées : un dossier mal imputé peut afficher une marge flatteuse et ne pas figurer ici.",
                    ],
                    kv: [
                      ["Marge constatée", `${formatPct(d.perc_marge_def, 1)} %`],
                      ["Marge prévue", `${formatPct(d.perc_marge_prov, 1)} %`],
                      ["Écart", `${formatPct(ecart, 1)} points`],
                      ["CA définitif", `${formatMFcfa(d.ca_definitif)} M FCFA`],
                      ["CA provisoire", `${formatMFcfa(d.ca_provisoire)} M FCFA`],
                      ["Client", d.client],
                    ],
                  },
                };
              })}
            />
            <Reste
              affiches={margesFaibles.length}
              total={dossiersMesurables.length}
              nom="dossiers facturés"
            />
            <Note style={{ marginTop: 14 }}>
              Classement sur les dossiers facturés de l&apos;échantillon servi par le tableau de bord des
              marges.
              {nbArtefacts > 0 &&
                ` ${formatNumber(nbArtefacts)} dossier(s) affichant une marge sous ${formatPct(MARGE_PLANCHER_PCT, 0)} % sont écartés : à ce niveau, le taux traduit une dépense imputée sur un dossier dont le chiffre d'affaires a été facturé ailleurs, pas une perte d'exploitation.`}
            </Note>
          </Tile>
        )}

      </Bento>
    </>
  );
}
