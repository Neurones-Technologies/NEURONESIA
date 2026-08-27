import { getArbitrageDossier } from "@/lib/api/arbitrage";
import type { ArbitrageDossier, PayeurProfile } from "@/lib/api/arbitrage";
import { formatDate, formatMFcfa, formatNumber, mFcfa } from "@/lib/format";
import { ProfileKey } from "@/lib/types";
import { Clickable } from "@/components/ui/detail";
import { Note, Tag } from "@/components/ui/primitives";
import { ContexteForm } from "./ContexteForm";
import { DecisionCockpit, type OptionVM } from "./DecisionCockpit";
import { optionDetail, payeurDetail } from "./details";
import {
  ACTIF_LABELS,
  CONSEQUENCE_LABELS,
  NATURE_VARIANT,
  PAYEUR_PORTEE,
  PAYEUR_VARIANT,
  STATUS_LABELS,
  VERDICT_LABELS,
  payeurTrajectoire,
  prioriteVariant,
  roleLabel,
  signalSummary,
  statusVariant,
} from "./shared";

/** Étape numérotée du dossier. L'écran empilait dix blocs de même poids
 * visuel : rien ne disait dans quel ordre les lire, ni où finissait le constat
 * et où commençait la décision. */
function Step({ n, title, sub }: { n: string; title: string; sub?: string }) {
  return (
    <p className="arb-step">
      <i>{n}</i>
      <b>{title}</b>
      {sub && <span>{sub}</span>}
    </p>
  );
}

/** Bandeau de lecture du comportement de paiement, placé avant les montants :
 * c'est lui qui décide de la conduite à tenir, les montants disent seulement
 * combien elle pèse. */
function PayeurBandeau({ profil, subjectRef }: { profil: PayeurProfile; subjectRef: string }) {
  const t = payeurTrajectoire(profil);
  const variant = PAYEUR_VARIANT[profil.classe] ?? "n";
  return (
    <Clickable className={`pay pay--${variant}`} detail={payeurDetail(profil, subjectRef)}>
      <div className="pay-m">
        <span className="pay-l">{t.label}</span>
        <span className="pay-t">
          {t.avant && (
            <>
              <s>{t.avant}</s>
              <i>→</i>
            </>
          )}
          <b>{t.valeur}</b>
        </span>
        {t.rappel && <span className="pay-r">{t.rappel}</span>}
      </div>
      <div className="pay-c">
        <div className="pay-tags">
          <Tag variant={variant}>{profil.classe_label}</Tag>
          <Tag variant={NATURE_VARIANT[profil.nature] ?? "n"}>{profil.nature}</Tag>
        </div>
        {/* La conduite à tenir avant la démonstration qui la fonde : c'est la
            seule ligne du bandeau qui dise quoi faire, elle était rendue dans le
            style le plus discret du bloc. */}
        <p className="pay-do">{PAYEUR_PORTEE[profil.classe]}</p>
        <p className="pay-b">{profil.lecture}</p>
        <p className="pay-more">Détail des délais mesurés</p>
      </div>
    </Clickable>
  );
}

/** Instruction du dossier sélectionné — SEULE partie de l'écran qui attend le LLM.
 *
 * `/v1/arbitrage/dossier/{ref}` bloque sur deux appels Claude Sonnet (avocat du
 * contraire + formulation de l'échéancier, cf. uc_arbitrage/narratif.py). Tant
 * que ce composant vivait dans le corps d'`ArbitrageView`, ces secondes
 * retenaient TOUT le HTML de la page — KPI et file d'arbitrage compris, alors
 * que le backend les produit en 0,3 s (mesuré sur `_compute_all_candidates`).
 *
 * Même raison et même patron qu'`AnalysisSlot` (components/ui/analysis-slot.tsx)
 * pour les narrations du cockpit : ne PAS remettre cet appel dans le
 * `Promise.all` du parent sous prétexte que le cache de narration le rend
 * souvent rapide — il ne l'est pas au premier passage, ni après une sync, ni
 * quand la fenêtre de 900 s est retombée.
 *
 * ATTENTION : le streaming n'atteint le navigateur que si le proxy ne tamponne
 * pas la réponse — `proxy_buffering off` sur `location /`
 * (nginx.neurones-ia.conf).
 */
export async function DossierPanel({
  subjectRef,
  profile,
  seuilM,
  isAdmin,
}: {
  subjectRef: string;
  profile: ProfileKey;
  seuilM: number;
  isAdmin: boolean;
}) {
  const dossier = await getArbitrageDossier(subjectRef);
  const recommended = dossier?.options.find((o) => o.recommandee);

  if (!dossier) {
    return (
      <div className="dec">
        <div className="dec-b">
          <Note style={{ marginTop: 0 }}>
            Ce dossier n&apos;est plus dans la file : le conflit a disparu du miroir (règlement encaissé, signal
            commercial clos) ou le client n&apos;est plus en retard. Choisissez un autre dossier dans la file.
          </Note>
        </div>
      </div>
    );
  }

  // Trancher relève de la seule Direction générale. Le mandat (`mandat_role`)
  // continue de dire quelle direction instruit le dossier — il est affiché en
  // tête, journalisé avec la décision et sert à ordonner la file — mais il
  // n'ouvre plus le droit d'engager l'entreprise : au-dessus comme en dessous du
  // seuil d'enjeu, c'est la DG qui arrête l'option retenue. Les autres profils
  // gardent le dossier entier en lecture et peuvent y verser du contexte terrain
  // (étape 05), qui n'a jamais demandé de mandat.
  //
  // Même règle côté serveur (`router._require_decision_authority`) : ce test-ci
  // n'évite qu'un aller-retour, il n'autorise rien à lui seul.
  const peutTrancher = isAdmin || profile === "dg";
  const enjeuM = mFcfa(dossier.enjeu_xof);
  const ratio = (dossier.profil_payeur.cout_report_ratio_semaine * 100).toFixed(1);

  const options: OptionVM[] = dossier.options.map((opt) => ({
    code: opt.code,
    titre: opt.titre,
    description: opt.description,
    argumentaire: opt.argumentaire,
    repli: opt.redige_par === "repli",
    recommandee: opt.recommandee,
    value: `${opt.code} · ${opt.titre}`,
    consequences: opt.consequences.map((c) => ({
      role: roleLabel(c.role),
      text: c.text,
      variant: c.variant,
      verdict: CONSEQUENCE_LABELS[c.variant] ?? c.variant,
    })),
    detail: optionDetail(opt, dossier),
  }));

  return (
    <div className="dec">
      <div className="dec-h">
        <div className="arb-hd">
          <h3>{dossier.subject_label}</h3>
          <div className="arb-hd-t">
            <Tag variant={prioriteVariant(dossier.priorite.niveau)}>{dossier.priorite.label}</Tag>
            <Tag variant="n">mandat {roleLabel(dossier.mandat_role)}</Tag>
          </div>
        </div>

        <div className="arb-facts">
          <div className="arb-fact">
            <span>Impayé constaté</span>
            <b>{formatMFcfa(dossier.impaye_xof)} M</b>
            <i>
              {formatNumber(dossier.impaye_nb_factures)} facture(s) · mesuré
            </i>
          </div>
          <div className="arb-fact">
            <span>Enjeu commercial</span>
            <b>{formatMFcfa(dossier.enjeu_xof)} M</b>
            <i>
              {dossier.signal_type.toLowerCase()} · {dossier.signal_nature}
            </i>
          </div>
          <div className="arb-fact">
            <span>Coût du report</span>
            <b>≈ {formatMFcfa(dossier.cout_report_xof_semaine)} M</b>
            <i>par semaine · {ratio} % de l&apos;enjeu</i>
          </div>
          <div className="arb-fact">
            <span>Comportement de paiement</span>
            <b className="arb-fact-w">{dossier.profil_payeur.classe_label}</b>
            <i>{PAYEUR_PORTEE[dossier.profil_payeur.classe]}</i>
          </div>
        </div>

        <p>
          Le mandat revient à {roleLabel(dossier.mandat_role)} : l&apos;enjeu de {formatNumber(enjeuM)} M FCFA{" "}
          {enjeuM >= seuilM ? "dépasse" : "reste sous"} le seuil de {formatNumber(seuilM)} M au-delà duquel aucune
          direction ne tranche seule. Priorité {dossier.priorite.label} — {dossier.priorite.raison}. Le coût du
          report est une estimation calibrée sur le comportement de paiement de ce client, pas un montant à
          provisionner.
          {dossier.commercial_compte ? ` Compte suivi par ${dossier.commercial_compte}.` : ""}
        </p>
      </div>

      <div className="dec-b">
        <Step n="01" title="Ce que ce client paie réellement" sub="la lecture qui décide de la conduite à tenir" />
        <PayeurBandeau profil={dossier.profil_payeur} subjectRef={dossier.subject_ref} />

        <Step n="02" title="Les deux montants en présence" sub="à ne pas confondre : l'un est dû, l'autre est en jeu" />
        <div className="rows arb-mb">
          <div className="row-m">
            <div>
              <div className="row-n">Impayé constaté</div>
              <div className="row-s">
                {formatNumber(dossier.impaye_nb_factures)} facture(s) échue(s) · retard le plus ancien{" "}
                {formatNumber(dossier.retard_max_jours)} jours
              </div>
            </div>
            <div className="num">{formatMFcfa(dossier.impaye_xof)} M FCFA</div>
            <Tag variant={NATURE_VARIANT.mesuré}>mesuré</Tag>
          </div>
          <div className="row-m">
            <div>
              <div className="row-n">Enjeu commercial ({dossier.signal_type.toLowerCase()})</div>
              <div className="row-s">{signalSummary(dossier)}</div>
            </div>
            <div className="num">{formatMFcfa(dossier.enjeu_xof)} M FCFA</div>
            <Tag variant={NATURE_VARIANT[dossier.signal_nature] ?? "w"}>{dossier.signal_nature}</Tag>
          </div>
        </div>

        <Step n="03" title="Positions en présence" sub="les deux lectures sont vraies, elles ne peuvent pas être suivies ensemble" />
        <div className="rows arb-mb">
          {dossier.positions.map((p, i) => (
            <div className="row" key={i}>
              <div className="cons" style={{ border: 0, padding: 0 }}>
                <i>{roleLabel(p.role)}</i>
                <span>{p.text}</span>
                {p.nature && (
                  <span className={`tag tag--${NATURE_VARIANT[p.nature] ?? "n"}`} style={{ fontSize: 9 }}>
                    {p.nature}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>

        <Step
          n="04"
          title="Objections et angles morts"
          sub={
            recommended
              ? `raisons de ne pas suivre l'option ${recommended.code}, et ce qui manque encore pour trancher`
              : "ce qui plaide contre, et ce qui manque encore pour trancher"
          }
        />
        <div className="split arb-mb">
          <div>
            <p className="mini-l">Avocat du contraire</p>
            <div className="rows">
              {dossier.contre_arguments.map((c, i) => (
                <div className="row" key={i}>
                  <div className="row-s" style={{ margin: 0 }}>
                    {c}
                  </div>
                  <span className="ro">{String(i + 1).padStart(2, "0")}</span>
                </div>
              ))}
              {dossier.contre_arguments.length === 0 && (
                <div className="row">
                  <div className="row-s" style={{ margin: 0 }}>
                    Aucun contre-argument identifié sur ce dossier.
                  </div>
                </div>
              )}
            </div>
          </div>
          <div>
            <p className="mini-l">Ce qui manque pour trancher</p>
            <ManqueListe dossier={dossier} />
          </div>
        </div>

        <Step n="05" title="Contexte terrain" sub="ce que seul le compte peut dire — aucun mandat requis" />
        <ContextesDeposes dossier={dossier} />
        <ContexteForm
          profile={profile}
          subjectRef={dossier.subject_ref}
          commercialCompte={dossier.commercial_compte}
        />

        <Step
          n="06"
          title="Trancher"
          sub={
            peutTrancher
              ? "le cockpit classe les options, il ne décide pas : l'écart à la recommandation est journalisé, jamais empêché"
              : "cette décision revient à la Direction générale — le dossier s'instruit ici, il se tranche là"
          }
        />
        <DecisionsLiees dossier={dossier} />

        {peutTrancher && recommended ? (
          <DecisionCockpit
            options={options}
            recommandee={`${recommended.code} · ${recommended.titre}`}
            ecartNote="le registre conserve ce que le cockpit recommandait et ce que vous avez retenu, et c'est la comparaison des deux qui rend son taux de fiabilité interprétable."
            hidden={{
              profile,
              title: `Arbitrage ${dossier.subject_ref}`,
              context: dossier.subject_label,
              subject_ref: dossier.subject_ref,
              subject_label: dossier.subject_label,
              enjeu_xof: String(dossier.enjeu_xof),
              cout_report_xof_semaine: String(dossier.cout_report_xof_semaine),
              mandat_role: dossier.mandat_role,
              profils_impliques: dossier.profils_impliques.join(","),
              profil_payeur_classe: dossier.profil_payeur.classe,
            }}
          />
        ) : (
          <>
            <OptionsLecture options={options} />
            <Note>
              {recommended
                ? `Seule la Direction générale tranche un arbitrage — dossier visible pour information, non actionnable depuis ce profil. Il est instruit sous le mandat de ${roleLabel(dossier.mandat_role)} : c'est cette direction qui le porte en comité, la décision d'engager restant à la DG.`
                : "Ce dossier ne porte aucune option exploitable : rien n'y est actionnable pour le moment."}{" "}
              Le serveur refuse toute journalisation et toute clôture de revue à un profil autre que la
              Direction générale, quel que soit l&apos;écran d&apos;où elles sont tentées. Vous pouvez en
              revanche apporter le contexte terrain ci-dessus : cela ne demande aucun mandat.
            </Note>
          </>
        )}
      </div>
    </div>
  );
}

/** Ce qui manque pour trancher : une question, qui la détient, sous quel délai.
 *
 * Ces lignes étaient rendues en `.row-m` (grille `1.6fr 1fr auto`), forme faite
 * pour un libellé court suivi d'un montant. Ici la première cellule porte une
 * question de deux ou trois lignes tandis que la deuxième, en `white-space:
 * nowrap`, réserve la largeur entière de « Compte (account manager) » — et une
 * piste `1fr` ne descend jamais sous son contenu minimum. Dans une demi-colonne
 * de `.split`, la question se retrouvait dans une gouttière de 110 px et
 * descendait sur quinze lignes.
 *
 * La question prend donc toute la largeur ; le porteur et le délai passent
 * dessous, sur une ligne de méta qui se replie au lieu de pousser. */
function ManqueListe({ dossier }: { dossier: ArbitrageDossier }) {
  if (dossier.manque.length === 0) {
    return (
      <div className="arb-gap">
        <div className="arb-gap-i">
          <p className="arb-gap-t">Le dossier est complet : rien ne bloque la décision côté données.</p>
        </div>
      </div>
    );
  }
  return (
    <ol className="arb-gap">
      {dossier.manque.map((m, i) => (
        <li className="arb-gap-i" key={i}>
          <p className="arb-gap-t">{m.text}</p>
          <div className="arb-gap-m">
            <span className="arb-gap-o">
              <i>à obtenir de</i> {m.owner}
            </span>
            <Tag variant="n">{m.delay}</Tag>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Contributions déjà versées sur ce dossier. Elles s'empilent : un motif qui
 * change entre deux comités est lui-même une information. */
function ContextesDeposes({ dossier }: { dossier: ArbitrageDossier }) {
  const contextes = dossier.contextes_terrain ?? [];
  if (contextes.length === 0) {
    return (
      <p className="arb-empty arb-empty--inline">
        Aucune contribution terrain sur ce dossier. Le miroir Odoo ne contient pas le motif d&apos;un retard : il
        ne peut venir que d&apos;un appel au client.
      </p>
    );
  }
  return (
    <div className="rows arb-mb">
      {contextes.map((c) => (
        <div className="row-m" key={c.id}>
          <div>
            <div className="row-n">{c.motif_retard || "— (aucun motif renseigné)"}</div>
            <div className="row-s">
              {roleLabel(c.created_role)} · {c.created_by}
              {c.created_at ? ` · ${formatDate(c.created_at)}` : ""}
            </div>
          </div>
          <div />
          {c.dossier_toujours_actif ? (
            <Tag variant={c.dossier_toujours_actif === "non" ? "r" : c.dossier_toujours_actif === "oui" ? "s" : "w"}>
              {ACTIF_LABELS[c.dossier_toujours_actif] ?? c.dossier_toujours_actif}
            </Tag>
          ) : (
            <span className="ro">—</span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Ce qui a déjà été décidé sur ce client. Le dossier portait l'information sans
 * jamais l'afficher : on pouvait donc rouvrir un arbitrage en ignorant qu'un
 * échéancier avait été acté trois semaines plus tôt. */
function DecisionsLiees({ dossier }: { dossier: ArbitrageDossier }) {
  const liees = dossier.decisions_liees ?? [];
  if (liees.length === 0) return null;
  return (
    <div className="arb-prior">
      <p className="mini-l">Déjà décidé sur ce client</p>
      <div className="rows arb-mb">
        {liees.map((d) => (
          <div className="row-m" key={d.id}>
            <div>
              <div className="row-n">{d.option_retenue || d.title}</div>
              <div className="row-s">
                {d.created_by || "—"}
                {d.created_at ? ` · ${formatDate(d.created_at)}` : ""}
                {d.motif_decision ? ` · « ${d.motif_decision} »` : ""}
              </div>
            </div>
            <div className="nums">
              {d.review_verdict ? `revue ${VERDICT_LABELS[d.review_verdict] ?? d.review_verdict}` : "revue à faire"}
            </div>
            <Tag variant={statusVariant(d.status)}>{STATUS_LABELS[d.status] ?? d.status}</Tag>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Options en lecture seule, pour un profil sans mandat : le dossier reste
 * lisible et comparable, il n'est simplement pas actionnable ici. */
function OptionsLecture({ options }: { options: OptionVM[] }) {
  return (
    <div className="opts arb-mb">
      {options.map((opt) => (
        <div key={opt.code} className={`opt${opt.recommandee ? " reco" : ""}`}>
          <div className="opt-h">
            <span className="opt-n">Option {opt.code}</span>
            {opt.recommandee && <Tag variant="a">recommandée</Tag>}
          </div>
          <b className="opt-t">{opt.titre}</b>
          <div className="opt-d">{opt.description}</div>
          {opt.consequences.map((c, i) => (
            <div className={`ocons ocons--${c.variant}`} key={i}>
              <div className="ocons-h">
                <i>{c.role}</i>
                <span className={`tag tag--${c.variant}`}>{c.verdict}</span>
              </div>
              <div className="ocons-t">{c.text}</div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
