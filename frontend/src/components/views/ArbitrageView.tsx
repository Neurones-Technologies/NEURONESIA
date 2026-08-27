import Link from "next/link";
import { Suspense } from "react";

import { getArbitrageFile, getReliability, listDecisions } from "@/lib/api/arbitrage";
import type { ArbitrageCandidate } from "@/lib/api/arbitrage";
import { getMe } from "@/lib/api/me";
import { isAdminRole } from "@/lib/auth/roles";
import { META } from "@/lib/data/profiles";
import { formatNumber, mFcfa } from "@/lib/format";
import { ProfileKey } from "@/lib/types";
import { Aide } from "@/components/ui/aide";
import { StatTile } from "@/components/ui/bento";
import { Note, Section, ViewHeader } from "@/components/ui/primitives";
import { DossierPanel } from "@/components/views/arbitrage/DossierPanel";
import { DossierPending } from "@/components/views/arbitrage/DossierPending";
import { Worklist, type QueueItem } from "@/components/views/arbitrage/Worklist";
import { candidateDetail } from "@/components/views/arbitrage/details";
import {
  PAYEUR_VARIANT,
  isRowRelevant,
  roleLabel,
  roleShort,
  splitSujet,
  trajectoireCourte,
} from "@/components/views/arbitrage/shared";

/** Vue Arbitrages — connectée au backend réel (modules 26 à 29, cf.
 * `modules/uc_arbitrage`) : la file de dossiers est calculée en recoupant les
 * impayés (Direction financière) et les signaux commerciaux (renouvellement,
 * cross-sell) déjà produits par les autres modules — jamais un scénario inventé.
 *
 * L'écran est organisé dans l'ordre où on y travaille : choisir un dossier dans
 * la file (colonne de gauche, `Worklist`) puis l'instruire (`DossierPanel`). Le
 * tableau du registre des décisions (`arbitrage/Registre.tsx`) n'est plus rendu
 * ici — seuls les taux de fiabilité qu'il alimentait restent affichés. Le
 * dossier ouvert vit dans l'URL (`?dossier=<ref>`) : il est partageable et
 * survit au rechargement, là où l'écran n'instruisait auparavant que le premier
 * dossier du périmètre, sans aucun moyen d'en ouvrir un autre.
 *
 * Trancher relève de la seule Direction générale : le cockpit de décision n'est
 * rendu que chez elle (cf. `DossierPanel.peutTrancher`) et le backend applique la
 * même règle à l'exécution (`create_decision` et `update_decision`, cf.
 * `router._require_decision_authority`). Le mandat (`mandat_role`) reste affiché
 * et journalisé — il dit quelle direction instruit le dossier et le porte en
 * comité, et il délimite le périmètre de chaque profil dans la file — mais il
 * n'ouvre plus le droit d'engager. Chaque chiffre affiché porte sa nature
 * (mesuré / observé / inféré) pour qu'une déduction ne se lise pas comme un fait. */

function queueItem(c: ArbitrageCandidate, rang: number, relevant: boolean, seuilM: number): QueueItem {
  const { client, conflit } = splitSujet(c.subject_label);
  return {
    ref: c.subject_ref,
    label: c.subject_label,
    client,
    conflit,
    rang,
    prioriteLabel: c.priorite.label,
    prioriteNiveau: c.priorite.niveau,
    prioriteRaison: c.priorite.raison,
    payeurLabel: c.profil_payeur.classe_label,
    payeurVariant: PAYEUR_VARIANT[c.profil_payeur.classe] ?? "n",
    trajectoire: trajectoireCourte(c.profil_payeur),
    mandatLabel: roleLabel(c.mandat_role),
    mandatCourt: roleShort(c.mandat_role),
    impayeM: mFcfa(c.impaye_xof),
    enjeuM: mFcfa(c.enjeu_xof),
    retardMax: c.retard_max_jours,
    relevant,
    detail: candidateDetail(c, seuilM),
  };
}

export async function ArbitrageView({ profile, selected }: { profile: ProfileKey; selected?: string }) {
  const [file, decisions, reliability, me] = await Promise.all([
    getArbitrageFile(),
    listDecisions(),
    getReliability(),
    getMe(),
  ]);

  if (!file) {
    return <Note>Ce module n&apos;est pas disponible pour votre profil.</Note>;
  }

  const isAdmin = isAdminRole(me.role);
  const seuilM = file.kpi.seuil_mandat_dg_m_fcfa;
  const basePath = `/${profile}/arbitrage`;

  const relevantCandidate = (c: ArbitrageCandidate) => isRowRelevant(profile, isAdmin, c.mandat_role, c.profils_impliques);
  const mesCandidats = file.candidats.filter(relevantCandidate);
  const monEnjeuM = mesCandidats.reduce((sum, c) => sum + mFcfa(c.enjeu_xof), 0);
  const monImpayeM = mesCandidats.reduce((sum, c) => sum + mFcfa(c.impaye_xof), 0);

  const items = file.candidats.map((c, i) => queueItem(c, i + 1, relevantCandidate(c), seuilM));
  // Le dossier demandé s'il existe encore dans la file, sinon celui de tête du
  // périmètre : un lien partagé sur un conflit résolu depuis ne doit pas ouvrir
  // un écran vide.
  const selectedRef =
    (selected && file.candidats.some((c) => c.subject_ref === selected) ? selected : null) ??
    mesCandidats[0]?.subject_ref ??
    file.candidats[0]?.subject_ref ??
    null;

  const registre = decisions ?? [];
  const revuesFaites = registre.filter((d) => Boolean(d.review_verdict)).length;
  const urgent = file.kpi.echeance_plus_proche_jours !== null && file.kpi.echeance_plus_proche_jours < 15;

  return (
    <>
      {/* <ViewHeader
        title="Arbitrages"
        subtitle={
          <>
            Les dossiers où deux lectures vraies du même client s&apos;opposent : des factures échues d&apos;un côté,
            un signal commercial actif de l&apos;autre. Le cockpit les ordonne, les documente et journalise ce qui
            est décidé — il ne tranche jamais à votre place.
          </>
        }
      /> */}

      <div className="kpi-row">
        <StatTile
          span={4}
          label="Dossiers ouverts"
          value={formatNumber(file.kpi.dossiers_ouverts)}
          unit="dossiers"
          aide="Le nombre de situations qui attendent une décision : un même client a des factures échues d'un côté et une opportunité commerciale active de l'autre. Relancer le recouvrement ou pousser la vente — les deux ne se font pas en même temps."
          reading={
            isAdmin
              ? "conflits détectés + décisions en cours"
              : `dont ${formatNumber(mesCandidats.length)} dans votre périmètre`
          }
          detail={{
            kicker: "Indicateur · file d'arbitrage",
            title: "Dossiers ouverts",
            tag: file.kpi.dossiers_ouverts > 0 ? "à trancher" : "file vide",
            tagVariant: file.kpi.dossiers_ouverts > 0 ? "a" : "s",
            body: [
              `La file compte ${formatNumber(file.candidats.length)} conflit(s) détecté(s) automatiquement et ${formatNumber(
                file.decisions_ouvertes.length
              )} décision(s) déjà ouverte(s) mais non refermée(s).`,
              "Un conflit est détecté quand un même client cumule des factures échues et un signal commercial actif : les deux lectures sont vraies, elles ne peuvent simplement pas être suivies en même temps.",
              `${formatNumber(mesCandidats.length)} de ces dossiers relèvent de votre périmètre (mandat ou position citée) — les KPI de ce bandeau restent, eux, calculés sur l'ensemble.`,
            ],
            kv: [
              ["Conflits détectés", formatNumber(file.candidats.length)],
              ["Dans votre périmètre", formatNumber(mesCandidats.length)],
              ["Décisions ouvertes", formatNumber(file.decisions_ouvertes.length)],
              ["Enjeu cumulé (tous profils)", `${formatNumber(file.kpi.enjeu_cumule_m_fcfa)} M FCFA`],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Enjeu cumulé"
          value={formatNumber(file.kpi.enjeu_cumule_m_fcfa)}
          unit="M FCFA"
          aide="Le montant commercial que ces dossiers mettent en jeu : renouvellements et commandes qui basculent selon ce qui sera décidé. Ce n'est pas la somme que les clients doivent."
          reading={isAdmin ? "tous profils confondus" : `dont ${formatNumber(monEnjeuM)} M dans votre périmètre`}
          detail={{
            kicker: "Indicateur · enjeu",
            title: "Enjeu cumulé en arbitrage",
            tag: `${formatNumber(file.kpi.dossiers_ouverts)} dossiers`,
            tagVariant: "a",
            body: [
              `Les dossiers ouverts portent ensemble sur ${formatNumber(
                file.kpi.enjeu_cumule_m_fcfa
              )} M FCFA de signaux commerciaux. Attention : c'est le montant que la décision déplace côté commerce, PAS le montant dû.`,
              `L'exposition financière réellement échue sur votre périmètre est de ${formatNumber(
                monImpayeM
              )} M FCFA — les deux échelles sont distinctes et doivent être lues séparément.`,
              `Au-delà de ${formatNumber(seuilM)} M FCFA d'enjeu, le mandat bascule automatiquement à la Direction générale : c'est ce seuil qui explique pourquoi la plupart des dossiers sont mandat DG.`,
            ],
            kv: [
              ["Enjeu cumulé (tous profils)", `${formatNumber(file.kpi.enjeu_cumule_m_fcfa)} M FCFA`],
              ["Enjeu de votre périmètre", `${formatNumber(monEnjeuM)} M FCFA`],
              ["Impayé de votre périmètre", `${formatNumber(monImpayeM)} M FCFA`],
              ["Seuil de mandat DG", `${formatNumber(seuilM)} M FCFA`],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Prochaine échéance"
          value={file.kpi.echeance_plus_proche_jours !== null ? formatNumber(file.kpi.echeance_plus_proche_jours) : "—"}
          unit="jours"
          aide="Dans combien de jours la décision déjà prise la plus urgente doit être réexaminée. En dessous de 15 jours, la fenêtre pour agir est courte. Les conflits pas encore tranchés, eux, n'ont pas de date."
          reading={
            file.kpi.echeance_plus_proche_jours === null
              ? "aucune décision ouverte n'est datée"
              : urgent
                ? "sous le seuil de 15 jours"
                : "au-delà du seuil de 15 jours"
          }
          readingVariant={file.kpi.echeance_plus_proche_jours === null ? undefined : urgent ? "neg" : "wat"}
          detail={{
            kicker: "Indicateur · délai",
            title: "Prochaine échéance de décision",
            tag: urgent ? "fenêtre courte" : "fenêtre tenable",
            tagVariant: urgent ? "r" : "w",
            body: [
              file.kpi.echeance_plus_proche_jours !== null
                ? `La décision ouverte la plus contrainte arrive à échéance de relecture dans ${formatNumber(
                    file.kpi.echeance_plus_proche_jours
                  )} jours.`
                : "Aucune décision ouverte ne porte de date. Toute décision journalisée depuis cet écran reçoit désormais une échéance de relecture à 30 jours ; les décisions antérieures à ce module n'en ont pas.",
              "Cet indicateur porte sur les décisions déjà prises et à relire, pas sur les conflits détectés : ces derniers n'ont aucune échéance contractuelle exploitable dans le miroir Odoo.",
            ],
            kv: [
              [
                "Jours restants",
                file.kpi.echeance_plus_proche_jours !== null ? formatNumber(file.kpi.echeance_plus_proche_jours) : "—",
              ],
              ["Seuil de vigilance", "15 jours"],
              ["Délai de relecture par défaut", "30 jours"],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Coût du report"
          value={`≈ ${formatNumber(file.kpi.cout_report_m_fcfa_semaine)}`}
          unit="M FCFA / semaine"
          aide="Ce que coûte, à peu près, chaque semaine où l'on ne tranche pas. C'est une estimation calculée à partir de l'enjeu et du comportement de paiement du client : elle sert à savoir quel dossier passe en premier, pas à provisionner un montant."
          reading="estimation calibrée par client, pas une mesure"
          readingVariant="wat"
          detail={{
            kicker: "Indicateur · coût de l'attente",
            title: "Coût du report",
            tag: "estimation",
            tagVariant: "w",
            body: [
              `Ne pas trancher coûterait environ ${formatNumber(
                file.kpi.cout_report_m_fcfa_semaine
              )} M FCFA par semaine, cumulés sur l'ensemble des dossiers ouverts.`,
              "Cela reste une convention de calcul, pas une mesure : un pourcentage de l'enjeu par semaine. Elle sert à comparer deux reports entre eux et à ordonner la file — jamais à provisionner un montant ni à alimenter un plan de trésorerie.",
              "Le taux n'est plus le même pour tous : il va de 0,5 % chez un client dont le rythme de paiement s'améliore à 5 % chez un client qui a cessé de payer. Un taux uniforme revenait à affirmer qu'attendre coûte autant dans les deux cas, alors que c'est précisément ce que la file doit distinguer.",
            ],
            kv: [
              ["Coût hebdomadaire estimé", `≈ ${formatNumber(file.kpi.cout_report_m_fcfa_semaine)} M FCFA`],
              ["Méthode", "% de l'enjeu par semaine, taux fonction du comportement de paiement du client"],
              ["Plage de taux", "0,5 % (rythme en amélioration) à 5 % (paiements arrêtés)"],
              ["Dossiers concernés", formatNumber(file.kpi.dossiers_ouverts)],
              ["Nature", "estimation, pas une mesure"],
            ],
          }}
        />
        <StatTile
          span={4}
          label="Revues en retard"
          value={formatNumber(file.kpi.revues_en_retard)}
          unit="décisions"
          aide="Une décision prise est censée être réexaminée à date fixe pour comparer ce qui s'est réellement passé à ce qui avait été recommandé. Ce chiffre compte celles dont la date est passée sans que ce bilan ait été fait."
          reading={
            file.kpi.revues_en_retard > 0
              ? "échéance de relecture dépassée"
              : `${formatNumber(revuesFaites)} revue(s) faite(s) sur ${formatNumber(registre.length)} décision(s)`
          }
          readingVariant={file.kpi.revues_en_retard > 0 ? "wat" : undefined}
          detail={{
            kicker: "Indicateur · registre",
            title: "Revues en retard",
            tag: file.kpi.revues_en_retard > 0 ? "à instruire" : "aucune en retard",
            tagVariant: file.kpi.revues_en_retard > 0 ? "w" : "n",
            body: [
              file.kpi.revues_en_retard > 0
                ? `${formatNumber(
                    file.kpi.revues_en_retard
                  )} décision(s) ont dépassé leur échéance de relecture sans verdict enregistré. Tant qu'elles ne sont pas relues, elles ne recalibrent rien.`
                : `Aucune décision n'a dépassé son échéance de relecture. À ne pas lire comme « tout a été relu » : ${formatNumber(
                    revuesFaites
                  )} revue(s) ont été réellement faites sur ${formatNumber(registre.length)} décision(s) au registre.`,
              "La revue est le seul mécanisme qui rend l'outil vérifiable après coup : elle compare l'issue constatée à ce qui avait été recommandé. Son verdict est choisi par celui qui a le mandat, jamais imposé par l'outil.",
            ],
            kv: [
              ["Revues en retard", formatNumber(file.kpi.revues_en_retard)],
              ["Décisions au registre", formatNumber(registre.length)],
              ["Revues faites", formatNumber(revuesFaites)],
              ["Sans date de relecture", formatNumber(registre.filter((d) => !d.review_date).length)],
            ],
          }}
        />
      </div>

      <Section id="file" title="File d'arbitrage" subtitle="conflits détectés par recoupement, ordonnés par priorité de traitement">
        {/* Une file rétrécie par un réglage ne doit jamais se lire comme une file
            vide : ce que les conditions écartent est dit ici, avec le chemin pour
            le défaire. Les KPI ci-dessus, eux, restent ceux de la file entière. */}
        {file.filtre.nb_ecartes > 0 && items.length > 0 && (
          <Note style={{ marginTop: 0 }}>
            {formatNumber(file.filtre.nb_ecartes)} dossier(s) sur {formatNumber(file.filtre.nb_total)} sont écartés
            par les {file.filtre.conditions_actives.length} condition(s) d&apos;entrée actives de votre profil. Les
            indicateurs ci-dessus restent calculés sur la file entière. Réglage :{" "}
            <Link href={`/${profile}/params`}>écran Réglages</Link>.
          </Note>
        )}
        {items.length === 0 ? (
          file.filtre.conditions_actives.length > 0 ? (
            <Note style={{ marginTop: 0 }}>
              Aucun des {formatNumber(file.filtre.nb_total)} dossier(s) de la file ne satisfait les{" "}
              {file.filtre.conditions_actives.length} condition(s) d&apos;entrée actives de votre profil. Elles se
              combinent en ET : deux conditions défendables séparément peuvent ne laisser passer personne. Décochez-en
              une depuis l&apos;<Link href={`/${profile}/params`}>écran Réglages</Link>.
            </Note>
          ) : (
            <Note style={{ marginTop: 0 }}>
              Aucun conflit détecté actuellement — aucun client en retard de paiement ne cumule un signal commercial
              actif. À noter : ce module ne détecte à ce jour qu&apos;un seul type de tension. Les conflits propres à
              la livraison (plan de charge, fournisseurs, staffing) ne sont pas encore modélisés : leur absence ici ne
              signifie donc pas qu&apos;il n&apos;y en a aucun.
            </Note>
          )
        ) : (
          <div className="arb-work">
            <Worklist
              items={items}
              selectedRef={selectedRef}
              basePath={basePath}
              perimeterLabel={META[profile].name}
            />
            <div className="arb-stage">
              {selectedRef ? (
                <Suspense key={selectedRef} fallback={<DossierPending />}>
                  <DossierPanel subjectRef={selectedRef} profile={profile} seuilM={seuilM} isAdmin={isAdmin} />
                </Suspense>
              ) : (
                <Note style={{ marginTop: 0 }}>Choisissez un dossier dans la file pour l&apos;instruire.</Note>
              )}
            </div>
          </div>
        )}
      </Section>

      <Section
        id="registre"
        title="Fiabilité des recommandations"
        subtitle="ce que la relecture des décisions déjà prises dit de l'outil"
      >
        {reliability && (
          <div className="arb-rel">
            <div className="arb-rel-c">
              <span>
                Recommandations suivies
                <Aide id="reco-suivies">
                Sur les décisions déjà prises, la part où le mandataire a effectivement retenu l&apos;option que le
                cockpit recommandait. Un taux bas ne dit pas que l&apos;outil a tort : il dit que ses propositions ne
                sont pas suivies.
              </Aide>
              </span>
              <b>{reliability.taux_suivi_pct !== null ? `${reliability.taux_suivi_pct} %` : "—"}</b>
              <i>
                {formatNumber(reliability.nb_reco_suivies)} sur {formatNumber(reliability.nb_decisions_tracees)}{" "}
                décision(s) tracée(s)
              </i>
            </div>
            <div className="arb-rel-c">
              <span>
                Recommandations confirmées à la revue
                <Aide id="reco-confirmees">
                Quand on rouvre une décision quelques semaines plus tard pour regarder ce qui s&apos;est réellement
                passé, la part des cas où la recommandation s&apos;avère avoir été la bonne.
              </Aide>
              </span>
              <b>{reliability.taux_confirmation_pct !== null ? `${reliability.taux_confirmation_pct} %` : "—"}</b>
              <i>
                {formatNumber(reliability.nb_confirmees)} sur {formatNumber(reliability.nb_decisions_revues)} revue(s)
                faite(s)
              </i>
            </div>
            <div className="arb-rel-c">
              <span>
                Confirmées parmi les recommandations suivies
                <Aide id="reco-confirmees-parmi-suivies">
                Le même taux, mais en ne gardant que les décisions où la recommandation a été suivie. C&apos;est le seul
                chiffre qui mesure l&apos;outil : ailleurs, on mesure surtout le jugement de celui qui a tranché.
              </Aide>
              </span>
              <b>
                {reliability.taux_confirmation_reco_suivie_pct !== null
                  ? `${reliability.taux_confirmation_reco_suivie_pct} %`
                  : "—"}
              </b>
              <i>
                sur {formatNumber(reliability.nb_suivies_revues)} revue(s) — les seules qui disent quelque chose de
                l&apos;outil plutôt que du mandataire
              </i>
            </div>
            <p className="arb-rel-n">
              {reliability.historique_suffisant
                ? reliability.note
                : `${reliability.note} ${reliability.note_suivi}`}
            </p>
          </div>
        )}
      </Section>
    </>
  );
}
