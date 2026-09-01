import { getPilotageDg } from "@/lib/api/dashboard";
import { formatDate, formatFcfa, formatNumber, formatPct } from "@/lib/format";
import { Bars, Bento, StatTile, Tile } from "@/components/ui/bento";
import { Narr, Section } from "@/components/ui/primitives";
import { MOIS_ABREV, toSpark } from "./commun";

/** Pilotage de l'activité (vue 360) du DG.
 *
 * Miroir de l'onglet Réglages : les dix éléments « vue 360 » du débrief DG
 * lisent les MÊMES agrégats (GET /v1/dashboard/pilotage ↔ uc_briefing/facts.py
 * blocs 10-19) — jamais deux calculs différents pour le même indicateur. */
export async function DgPilotage() {
  const year = new Date().getFullYear();
  // `pilotage` est null si le module `dashboard` est refusé au rôle (403 absorbé).
  const pilotage = await getPilotageDg(year);

  const meilleureAnnee =
    pilotage && pilotage.ca_annuel.length
      ? pilotage.ca_annuel.reduce((a, b) => (b.ca_xof > a.ca_xof ? b : a))
      : null;
  const anneeCourante =
    pilotage && pilotage.ca_annuel.length
      ? pilotage.ca_annuel[pilotage.ca_annuel.length - 1]
      : null;
  const partMeilleurePct =
    meilleureAnnee && anneeCourante && meilleureAnnee.ca_xof
      ? (anneeCourante.ca_xof / meilleureAnnee.ca_xof) * 100
      : null;
  // Le DSO peut revenir en `{error}` quand le miroir n'a aucune facture.
  const encaissement =
    pilotage && !("error" in pilotage.encaissement) ? pilotage.encaissement : null;
  const commerciauxActifs = (pilotage?.commerciaux ?? []).filter((c) => c.ca_total_xof > 0);
  const commerciauxTotal = commerciauxActifs.reduce((s, c) => s + c.ca_total_xof, 0);
  const maxCommercial = Math.max(...commerciauxActifs.map((c) => c.ca_total_xof), 0);
  const maxMensuel = Math.max(...(pilotage?.mensuel ?? []).map((m) => m.ca_xof), 0);
  const prochaineEcheance = pilotage?.echeances.prochaines[0] ?? null;

  return (
    <Section
      id="pilotage"
      title="Pilotage de l'activité"
      subtitle="La vue 360 pour décider — trajectoire, efficacité commerciale, encaissement"
    >
      {pilotage && meilleureAnnee && anneeCourante ? (
        <Bento>
          <StatTile
            span={4}
            rang="principal"
            label="CA pluriannuel"
            aide="Le CA commandé des cinq derniers exercices. Il situe l'année en cours dans la trajectoire, plutôt que de la juger seule."
            value={formatFcfa(meilleureAnnee.ca_xof)}
            unit={`FCFA · meilleure année ${meilleureAnnee.annee}`}
            reading={
              meilleureAnnee.annee === anneeCourante.annee
                ? "l'exercice en cours est déjà le meilleur des cinq"
                : partMeilleurePct !== null
                  ? `exercice en cours (incomplet) : ${formatFcfa(anneeCourante.ca_xof)} FCFA, soit ${formatPct(partMeilleurePct, 0)} % de la meilleure année`
                  : undefined
            }
            spark={toSpark(pilotage.ca_annuel.map((a) => a.ca_xof))}
            sparkAxis={pilotage.ca_annuel.map((a) => String(a.annee))}
            sparkLabels={pilotage.ca_annuel.map(
              (a) =>
                `${a.annee} : ${formatFcfa(a.ca_xof)} FCFA (${formatNumber(a.nb_commandes)} commande(s))`
            )}
          />
          <StatTile
            span={4}
            label={`Atterrissage ${pilotage.atterrissage.trimestre ?? "du trimestre"}`}
            aide="Le CA déjà commandé sur le trimestre en cours, prolongé par la tendance des six derniers mois. Une projection, pas une promesse."
            value={formatFcfa(pilotage.atterrissage.projection_fin_trimestre?.realiste_xof ?? 0)}
            unit="FCFA en scénario réaliste"
            reading={`déjà commandé : ${formatFcfa(pilotage.atterrissage.realise_a_ce_jour_xof ?? 0)} FCFA · fourchette ${formatFcfa(pilotage.atterrissage.projection_fin_trimestre?.pessimiste_xof ?? 0)} à ${formatFcfa(pilotage.atterrissage.projection_fin_trimestre?.optimiste_xof ?? 0)} FCFA`}
          />
          <StatTile
            span={4}
            label="Transformation commerciale"
            aide="La part des opportunités gagnées. Le taux en valeur pèse les montants : perdre une grosse affaire y compte plus que perdre trois petites."
            value={formatPct(pilotage.transformation.win_rate?.taux_nb_pct ?? null, 0)}
            unit="% des affaires gagnées en nombre"
            reading={
              `${formatPct(pilotage.transformation.win_rate?.taux_valeur_pct ?? null, 0)} % en valeur` +
              (pilotage.transformation.pertes?.by_client?.[0]
                ? ` · ${pilotage.transformation.pertes.by_client[0].client} concentre le plus de pertes (${formatFcfa(pilotage.transformation.pertes.by_client[0].montant_xof)} FCFA)`
                : "")
            }
            readingVariant={
              (pilotage.transformation.win_rate?.taux_valeur_pct ?? 100) < 30 ? "neg" : undefined
            }
          />

          <StatTile
            span={4}
            label={`Marge ${pilotage.annee}`}
            aide="La marge des dossiers ouverts sur l'exercice : annoncée à l'ouverture (provisoire), puis constatée à l'arrêté (définitive)."
            value={formatFcfa(pilotage.marge?.marge_provisoire_total ?? 0)}
            // Taux agrégés (`taux_marge_*`), jamais `perc_marge_*_moyen` : ces
            // derniers moyennent des pourcentages par dossier et valent -745 %
            // sur ce miroir. Cf. l'adaptateur, `get_margin_stats`.
            unit={`FCFA provisoires · ${formatPct(pilotage.marge?.taux_marge_provisoire_pct ?? null, 1)} % du CA`}
            // La définitive n'est publiée que si la dépense est imputée sur une
            // part suffisante du CA : sinon la tuile annonce la couverture. Un
            // dossier sans dépense imputée affiche 100 % de marge par construction.
            reading={
              pilotage.marge?.marge_definitive_exploitable
                ? `définitive constatée : ${formatFcfa(pilotage.marge?.marge_definitive_total ?? 0)} FCFA (${formatPct(pilotage.marge?.taux_marge_definitive_pct ?? null, 1)} % du CA) sur ${formatNumber(pilotage.marge?.nb_dossiers_marge_imputee ?? 0)} dossiers imputés`
                : `définitive non exploitable : dépense imputée sur ${formatPct(pilotage.marge?.couverture_marge_definitive_pct ?? null, 1)} % du CA facturé (seuil ${formatPct(pilotage.marge?.seuil_couverture_marge_pct ?? null, 0)} %)`
            }
          />
          <StatTile
            span={4}
            label="Délai d'encaissement"
            aide="Le temps réel entre l'émission d'une facture et son paiement. Chaque jour de plus est de la trésorerie immobilisée."
            value={
              encaissement?.delai_moyen_recouvrement_reel_jours !== null &&
              encaissement?.delai_moyen_recouvrement_reel_jours !== undefined
                ? formatNumber(encaissement.delai_moyen_recouvrement_reel_jours)
                : "—"
            }
            unit="jours en moyenne"
            reading={
              encaissement
                ? `${formatPct(encaissement.taux_recouvrement_pct, 0)} % des factures recouvrées · ${formatFcfa(encaissement.montant_en_attente_xof)} FCFA en attente · retard moyen des impayés ${formatNumber(encaissement.retard_moyen_impayes_jours)} j`
                : "aucune facture dans le miroir"
            }
            readingVariant={
              encaissement && encaissement.retard_moyen_impayes_jours > 90 ? "neg" : undefined
            }
          />
          <StatTile
            span={4}
            label="Affaires à échéance"
            aide="Les opportunités encore ouvertes dont la date de clôture tombe dans les 60 prochains jours — celles qui se décident maintenant."
            value={formatNumber(pilotage.echeances.nb)}
            unit={`sous ${pilotage.echeances.fenetre_jours} jours · ${formatFcfa(pilotage.echeances.montant_xof)} FCFA`}
            reading={
              prochaineEcheance
                ? `la plus proche : ${prochaineEcheance.opportunite} (${prochaineEcheance.client}) le ${formatDate(prochaineEcheance.deadline)}`
                : "aucune échéance dans la fenêtre"
            }
          />

          {commerciauxActifs.length > 0 && (
            <Tile
              span={6}
              title="Top 5 des commerciaux par CA"
              kick={`${pilotage.annee} · réalisé`}
              aide="La répartition du CA commandé de l'exercice entre commerciaux. Aucun objectif n'étant saisi en base, c'est une répartition du réalisé, pas un taux d'atteinte."
            >
              <Bars
                replierApres={5}
                nom="commerciaux"
                rows={commerciauxActifs.map((co) => ({
                  name: co.commercial,
                  sub: `${formatNumber(co.nb_commandes)} commande(s) · ${formatPct(commerciauxTotal ? (co.ca_total_xof / commerciauxTotal) * 100 : null, 0)} % du réalisé`,
                  value: `${formatFcfa(co.ca_total_xof)}`,
                  pct: maxCommercial ? (co.ca_total_xof / maxCommercial) * 100 : 0,
                }))}
              />
            </Tile>
          )}

          {pilotage.mensuel.length > 0 && (
            <Tile
              span={6}
              title="Rythme mensuel"
              kick={`${pilotage.annee} · CA commandé par mois`}
              aide="Le CA commandé mois par mois. Un essoufflement se voit ici des mois avant de se voir au bilan — le mois en cours est toujours incomplet."
            >
              <Bars
                rows={pilotage.mensuel.map((m) => ({
                  name: MOIS_ABREV[m.mois - 1] ?? String(m.mois),
                  sub: `${formatNumber(m.nb_commandes)} commande(s)`,
                  value: `${formatFcfa(m.ca_xof)}`,
                  pct: maxMensuel ? (m.ca_xof / maxMensuel) * 100 : 0,
                }))}
              />
            </Tile>
          )}
        </Bento>
      ) : (
        <Bento>
          <Tile span={12} quiet title="Pilotage de l'activité">
            <Narr>
              Les indicateurs de pilotage ne sont pas accessibles depuis ce profil, ou le backend
              ne les expose pas encore — rechargez la page après redémarrage du serveur.
            </Narr>
          </Tile>
        </Bento>
      )}
    </Section>
  );
}
