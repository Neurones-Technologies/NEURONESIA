import { getArbitrageDossier, getArbitrageFile, getReliability, listDecisions } from "@/lib/api/arbitrage";
import { createDecisionAction, markReviewedAction } from "@/lib/actions/arbitrage";
import { META } from "@/lib/data/profiles";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { formatMFcfa, formatNumber } from "@/lib/format";
import { ProfileKey, Variant } from "@/lib/types";
import {
  Acts,
  Btn,
  Kpi,
  KpiStrip,
  MiniLabel,
  ModuleCard,
  Mods,
  Note,
  Split,
  Tag,
  ViewHeader,
  Wf,
} from "@/components/ui/primitives";

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

function statusVariant(status: string): Variant {
  if (status === "tranchee") return "s";
  if (status === "escaladee") return "r";
  if (status === "reportee" || status === "en_cours") return "w";
  return "n";
}

const STATUS_LABELS: Record<string, string> = {
  en_cours: "en cours",
  tranchee: "tranchée",
  reportee: "reportée",
  escaladee: "escaladée",
  suspendue: "suspendue",
};

export async function ArbitrageView({ profile }: { profile: ProfileKey }) {
  const meta = META[profile];
  const [file, decisions, reliability] = await Promise.all([
    getArbitrageFile(),
    listDecisions(),
    getReliability(),
  ]);

  if (!file) {
    return (
      <>
        <ViewHeader eyebrow={`Arbitrages · ${meta.name}`} title="Décider, pas seulement constater" subtitle="" />
        <Note>Ce module n&apos;est pas disponible pour votre profil.</Note>
      </>
    );
  }

  const topCandidate = file.candidats[0];
  const dossier = topCandidate ? await getArbitrageDossier(topCandidate.subject_ref) : null;
  const recommended = dossier?.options.find((o) => o.recommandee);

  return (
    <>
      <ViewHeader
        eyebrow={`Arbitrages · ${meta.name}`}
        title="Décider, pas seulement constater"
        subtitle="Un dossier naît quand deux profils prennent des positions incompatibles sur le même client — calculé en recoupant les signaux déjà produits par les autres modules (impayés, cross-sell, portefeuille)."
      />

      <KpiStrip>
        <Kpi label="Dossiers ouverts" value={formatNumber(file.kpi.dossiers_ouverts)} detail="conflits détectés + décisions en cours" />
        <Kpi label="Enjeu cumulé" value={formatNumber(file.kpi.enjeu_cumule_m_fcfa)} detail="M FCFA en arbitrage" />
        <Kpi
          label="Échéance la plus proche"
          value={file.kpi.echeance_plus_proche_jours !== null ? formatNumber(file.kpi.echeance_plus_proche_jours) : "—"}
          detail="jours"
          valueVariant={file.kpi.echeance_plus_proche_jours !== null && file.kpi.echeance_plus_proche_jours < 15 ? "r" : undefined}
        />
        <Kpi label="Coût du report" value={formatNumber(file.kpi.cout_report_m_fcfa_semaine)} detail="M FCFA par semaine (estimation)" valueVariant="r" />
        <Kpi label="Revues en retard" value={formatNumber(file.kpi.revues_en_retard)} detail="décisions non revues à échéance" valueVariant={file.kpi.revues_en_retard > 0 ? "w" : undefined} />
      </KpiStrip>

      <Mods>
        <ModuleCard
          n="26"
          title="File d'arbitrage"
          desc="Conflits détectés en temps réel (impayés vs signaux commerciaux) + décisions déjà ouvertes, classés par enjeu."
          engine="Calcul réel"
        >
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>Dossier</th>
                  <th>Profils</th>
                  <th className="r">Enjeu</th>
                  <th>Mandat</th>
                  <th>État</th>
                </tr>
              </thead>
              <tbody>
                {file.candidats.map((c) => (
                  <tr key={c.subject_ref}>
                    <td>{c.subject_label}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{c.profils_impliques.map(roleLabel).join(" · ")}</td>
                    <td className="r mono">{formatMFcfa(c.enjeu_xof)} M</td>
                    <td style={{ fontSize: 12.5 }}>{roleLabel(c.mandat_role)}</td>
                    <td><Tag variant="r">non tranché</Tag></td>
                  </tr>
                ))}
                {file.decisions_ouvertes.map((d) => (
                  <tr key={`d-${d.id}`}>
                    <td>{d.subject_label || d.title}</td>
                    <td className="mono" style={{ fontSize: 11 }}>{d.profils_impliques.map(roleLabel).join(" · ") || "—"}</td>
                    <td className="r mono">{d.enjeu_xof ? `${formatMFcfa(d.enjeu_xof)} M` : "—"}</td>
                    <td style={{ fontSize: 12.5 }}>{d.mandat_role ? roleLabel(d.mandat_role) : "—"}</td>
                    <td><Tag variant={statusVariant(d.status)}>{STATUS_LABELS[d.status] ?? d.status}</Tag></td>
                  </tr>
                ))}
                {file.candidats.length === 0 && file.decisions_ouvertes.length === 0 && (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--t2)" }}>
                      Aucun conflit détecté actuellement — aucun client en retard de paiement ne cumule un signal
                      commercial actif.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Note>
            Un dossier est détecté quand un client cumule des factures échues ET un signal commercial actif
            (renouvellement, cross-sell) — recoupement automatique, pas une liste saisie à la main.
          </Note>
        </ModuleCard>

        {dossier && recommended && (
          <ModuleCard
            n="27"
            title={`Dossier d'arbitrage · ${dossier.subject_ref}`}
            desc={dossier.subject_label}
            engine="Narration · options"
            llm
          >
            <MiniLabel>Positions en présence</MiniLabel>
            <div className="rows" style={{ marginBottom: 18 }}>
              {dossier.positions.map((p, i) => (
                <div className="row" key={i}>
                  <div>
                    <div className="pos" style={{ border: 0, padding: 0 }}>
                      <i>{roleLabel(p.role)}</i>
                      <span>{p.text}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <MiniLabel>Options et conséquences par profil</MiniLabel>
            <div className="opts">
              {dossier.options.map((opt) => (
                <div className={`opt${opt.recommandee ? " reco" : ""}`} key={opt.code}>
                  <div className="opt-h">
                    <span className="opt-n">{opt.code}</span>
                    <b>{opt.titre}</b>
                    {opt.recommandee && <Tag variant="a">recommandée</Tag>}
                  </div>
                  <div className="opt-d">{opt.description}</div>
                  {opt.consequences.map((c, i) => (
                    <div className="cons" key={i}>
                      <i>{roleLabel(c.role)}</i>
                      <span>{c.text}</span>
                      <span className={`tag tag--${c.variant}`} style={{ fontSize: 9 }}>
                        {c.variant === "s" ? "favorable" : c.variant === "r" ? "défavorable" : "incertain"}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            <MiniLabel style={{ marginTop: 20 }}>
              Avocat du contraire · raisons de ne pas suivre l&apos;option recommandée
            </MiniLabel>
            <div className="rows">
              {dossier.contre_arguments.map((c, i) => (
                <div className="row" key={i}>
                  <div>
                    <div className="row-s" style={{ margin: 0 }}>{c}</div>
                  </div>
                  <span className="ro">{i + 1}</span>
                </div>
              ))}
            </div>

            <MiniLabel style={{ marginTop: 18 }}>Ce qui manque pour trancher</MiniLabel>
            <div className="rows">
              {dossier.manque.map((m, i) => (
                <div className="row-m" key={i}>
                  <div>
                    <div className="row-s" style={{ margin: 0 }}>{m.text}</div>
                  </div>
                  <div className="nums">{m.owner}</div>
                  <Tag variant="n">{m.delay}</Tag>
                </div>
              ))}
            </div>

            <form action={createDecisionAction} style={{ marginTop: 14 }}>
              <input type="hidden" name="profile" value={profile} />
              <input type="hidden" name="title" value={`Arbitrage ${dossier.subject_ref}`} />
              <input type="hidden" name="context" value={dossier.subject_label} />
              <input type="hidden" name="subject_ref" value={dossier.subject_ref} />
              <input type="hidden" name="subject_label" value={dossier.subject_label} />
              <input type="hidden" name="enjeu_xof" value={dossier.enjeu_xof} />
              <input type="hidden" name="mandat_role" value={dossier.mandat_role} />
              <input type="hidden" name="profils_impliques" value={dossier.profils_impliques.join(",")} />
              <input type="hidden" name="option_retenue" value={`${recommended.code} · ${recommended.titre}`} />
              <Acts>
                <Btn primary type="submit">
                  Trancher et enregistrer l&apos;option {recommended.code}
                </Btn>
              </Acts>
            </form>
            <Note>
              Enregistrer crée une décision datée et attribuée dans le registre (module 28) — la seule façon de
              rendre ce choix auditable après coup.
            </Note>
          </ModuleCard>
        )}

        <ModuleCard
          n="28"
          title="Engagements et revues"
          desc="Registre complet des décisions prises — y compris celles antérieures à ce module."
          engine="registre"
        >
          <div style={{ overflowX: "auto" }}>
            <table className="tb">
              <thead>
                <tr>
                  <th>Décision</th>
                  <th>Créée le</th>
                  <th>Propriétaire</th>
                  <th>État</th>
                  <th>Revue</th>
                </tr>
              </thead>
              <tbody>
                {(decisions ?? []).map((d) => (
                  <tr key={d.id}>
                    <td>{d.title}</td>
                    <td className="mono">{d.created_at ? d.created_at.slice(0, 10) : "—"}</td>
                    <td>{d.owner || d.created_by}</td>
                    <td><Tag variant={statusVariant(d.status)}>{STATUS_LABELS[d.status] ?? d.status}</Tag></td>
                    <td>
                      {d.review_verdict ? (
                        <Tag variant={d.review_verdict === "confirme" ? "s" : d.review_verdict === "infirme" ? "r" : "w"}>
                          {d.review_verdict}
                        </Tag>
                      ) : d.status === "en_cours" ? (
                        <form action={markReviewedAction} style={{ display: "inline" }}>
                          <input type="hidden" name="profile" value={profile} />
                          <input type="hidden" name="decision_id" value={d.id} />
                          <input type="hidden" name="review_verdict" value="confirme" />
                          <button className="btn" type="submit" style={{ fontSize: 11, padding: "3px 8px" }}>
                            Marquer revue
                          </button>
                        </form>
                      ) : (
                        <span className="ro">—</span>
                      )}
                    </td>
                  </tr>
                ))}
                {(!decisions || decisions.length === 0) && (
                  <tr>
                    <td colSpan={5} style={{ color: "var(--t2)" }}>
                      Aucune décision enregistrée.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <Note>
            Une décision sans date de revue n&apos;est pas une décision, c&apos;est une intention. Le registre
            conserve tout, y compris les décisions antérieures à ce module.
          </Note>
        </ModuleCard>

        <ModuleCard
          n="29"
          title="Fiabilité des recommandations"
          desc="L'outil tient son propre score, calculé sur le registre réel de décisions revues."
          engine="registre"
        >
          {reliability && (
            <Split>
              <div>
                <MiniLabel>Taux de confirmation</MiniLabel>
                <Wf
                  label="Décisions revues"
                  variant={reliability.historique_suffisant ? "s" : "w"}
                  width={`${Math.min(reliability.taux_confirmation_pct ?? 0, 100)}%`}
                  value={reliability.taux_confirmation_pct !== null ? `${reliability.taux_confirmation_pct} %` : "—"}
                />
                <Note>{reliability.note}</Note>
              </div>
              <div>
                <MiniLabel>Ce que ce score signifie</MiniLabel>
                <Note style={{ marginTop: 0 }}>
                  Un score fiable exige un minimum de décisions revues (seuil : 5). Tant que l&apos;historique est
                  insuffisant, aucun taux n&apos;est affiché comme définitif — mieux vaut l&apos;absence de chiffre
                  qu&apos;un chiffre non représentatif.
                </Note>
              </div>
            </Split>
          )}
        </ModuleCard>
      </Mods>
    </>
  );
}
