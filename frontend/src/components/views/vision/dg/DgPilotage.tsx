import { getPilotageDg } from "@/lib/api/dashboard";
import { formatDate, formatMFcfa, formatNumber, formatPct } from "@/lib/format";
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
            value={formatMFcfa(meilleureAnnee.ca_xof)}
            unit={`M FCFA · meilleure année ${meilleureAnnee.annee}`}
            reading={
              meilleureAnnee.annee === anneeCourante.annee
                ? "l'exercice en cours est déjà le meilleur des cinq"
                : partMeilleurePct !== null
                  ? `exercice en cours (incomplet) : ${formatMFcfa(anneeCourante.ca_xof)} M FCFA, soit ${formatPct(partMeilleurePct, 0)} % de la meilleure année`
                  : undefined
            }
            spark={toSpark(pilotage.ca_annuel.map((a) => a.ca_xof))}
            sparkAxis={pilotage.ca_annuel.map((a) => String(a.annee))}
            sparkLabels={pilotage.ca_annuel.map(
              (a) =>
                `${a.annee} : ${formatMFcfa(a.ca_xof)} M FCFA (${formatNumber(a.nb_commandes)} commande(s))`
            )}
          />
          <StatTile
            span={4}
            label={`Atterrissage ${pilotage.atterrissage.trimestre ?? "du trimestre"}`}
            aide="Le CA déjà commandé sur le trimestre en cours, prolongé par la tendance des six derniers mois. Une projection, pas une promesse."
            value={formatMFcfa(pilotage.atterrissage.projection_fin_trimestre?.realiste_xof ?? 0)}
            unit="M FCFA en scénario réaliste"
            reading={`déjà commandé : ${formatMFcfa(pilotage.atterrissage.realise_a_ce_jour_xof ?? 0)} M FCFA · fourchette ${formatMFcfa(pilotage.atterrissage.projection_fin_trimestre?.pessimiste_xof ?? 0)} à ${formatMFcfa(pilotage.atterrissage.projection_fin_trimestre?.optimiste_xof ?? 0)} M FCFA`}
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
                ? ` · ${pilotage.transformation.pertes.by_client[0].client} concentre le plus de pertes (${formatMFcfa(pilotage.transformation.pertes.by_client[0].montant_xof)} M FCFA)`
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
            value={formatMFcfa(pilotage.marge?.marge_provisoire_total ?? 0)}
            unit={`M FCFA provisoires · moy. ${formatPct(pilotage.marge?.perc_marge_provisoire_moyen ?? null, 1)} %`}
            reading={`définitive constatée : ${formatMFcfa(pilotage.marge?.marge_definitive_total ?? 0)} M FCFA (moy. ${formatPct(pilotage.marge?.perc_marge_definitive_moyen ?? null, 1)} %) sur ${formatNumber(pilotage.marge?.nb_dossiers ?? 0)} dossiers`}
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
                ? `${formatPct(encaissement.taux_recouvrement_pct, 0)} % des factures recouvrées · ${formatMFcfa(encaissement.montant_en_attente_xof)} M FCFA en attente · retard moyen des impayés ${formatNumber(encaissement.retard_moyen_impayes_jours)} j`
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
            unit={`sous ${pilotage.echeances.fenetre_jours} jours · ${formatMFcfa(pilotage.echeances.montant_xof)} M FCFA`}
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
                  value: `${formatMFcfa(co.ca_total_xof)} M`,
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
                  value: `${formatMFcfa(m.ca_xof)} M`,
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
