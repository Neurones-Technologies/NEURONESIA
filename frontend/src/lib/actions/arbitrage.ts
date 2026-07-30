"use server";

import { revalidatePath } from "next/cache";
import { apiFetch } from "@/lib/api/client";

/** Issues possibles d'un passage en comité. `tranchee` engage, `reportee` et
 * `escaladee` ne tranchent pas mais laissent une trace datée et motivée —
 * l'écran ne proposait auparavant que « journaliser l'option recommandée », si
 * bien qu'un dossier non tranché était indistinguable d'un dossier oublié. */
const STATUTS = ["tranchee", "reportee", "escaladee"] as const;
type Statut = (typeof STATUTS)[number];

export async function createDecisionAction(formData: FormData) {
  const profile = String(formData.get("profile") ?? "");
  const statut = String(formData.get("status") ?? "tranchee");
  if (!STATUTS.includes(statut as Statut)) return;

  const motif = String(formData.get("motif_decision") ?? "").trim();
  // Même règle que le backend (422 sinon) : un report ou une escalade sans motif
  // ne laisse rien à juger à la revue. On s'arrête ici plutôt que d'envoyer une
  // requête qu'on sait devoir échouer.
  if ((statut === "reportee" || statut === "escaladee") && !motif) return;

  // Sur un report ou une escalade, aucune option n'est retenue : forcer celle
  // qui était cochée ferait apparaître au registre un engagement jamais pris.
  const optionRetenue =
    statut === "tranchee" ? String(formData.get("option_retenue") ?? "").trim() : "";
  if (statut === "tranchee" && !optionRetenue) return;

  const payload = {
    title: String(formData.get("title") ?? ""),
    context: String(formData.get("context") ?? ""),
    subject_ref: String(formData.get("subject_ref") ?? ""),
    subject_label: String(formData.get("subject_label") ?? ""),
    enjeu_xof: Number(formData.get("enjeu_xof") ?? 0),
    cout_report_xof_semaine: Number(formData.get("cout_report_xof_semaine") ?? 0),
    mandat_role: String(formData.get("mandat_role") ?? ""),
    profils_impliques: String(formData.get("profils_impliques") ?? "").split(",").filter(Boolean),
    option_retenue: optionRetenue,
    // Ce que l'outil recommandait, enregistré même quand le mandataire s'en
    // écarte : c'est la comparaison des deux qui rend le score de fiabilité
    // interprétable (cf. `store.reliability_stats`).
    option_recommandee: String(formData.get("option_recommandee") ?? ""),
    profil_payeur_classe: String(formData.get("profil_payeur_classe") ?? ""),
    motif_decision: motif,
    status: statut,
  };

  if (!payload.title) return;

  await apiFetch("/v1/arbitrage/decisions", {
    method: "POST",
    body: JSON.stringify(payload),
    allowForbidden: true,
  });

  if (profile) revalidatePath(`/${profile}/arbitrage`);
}

/** Verdicts acceptés par le backend (cf. `db/models.py::DecisionModel`). Un verdict
 * hors liste est refusé plutôt que réécrit en « confirme » : un score de fiabilité
 * dont le verdict est imposé ne mesure rien. */
const REVIEW_VERDICTS = ["confirme", "infirme", "partiel"] as const;

export async function markReviewedAction(formData: FormData) {
  const profile = String(formData.get("profile") ?? "");
  const id = formData.get("decision_id");
  if (!id) return;

  const verdict = String(formData.get("review_verdict") ?? "");
  if (!REVIEW_VERDICTS.includes(verdict as (typeof REVIEW_VERDICTS)[number])) return;

  await apiFetch(`/v1/arbitrage/decisions/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      status: "tranchee",
      // `review_date` n'est PAS réécrite ici : posée à la création, c'est l'échéance
      // de relecture. L'écraser à la date du clic effacerait le fait que la revue a
      // été faite en retard — exactement ce que `revues_en_retard` doit pouvoir dire.
      review_verdict: verdict,
      review_comment: String(formData.get("review_comment") ?? ""),
    }),
    allowForbidden: true,
  });

  if (profile) revalidatePath(`/${profile}/arbitrage`);
}

/** Dépose la contribution terrain du commercial du compte sur un dossier.
 *
 * Le dossier réclame explicitement le motif du retard en désignant le compte
 * comme responsable de l'information (cf. `aggregation.missing_info`) — sans que
 * rien ne permette de la fournir. C'est la seule action de cet écran ouverte à un
 * profil sans mandat, et c'est voulu : le mandat conditionne le droit d'engager
 * l'entreprise, pas celui d'apporter un fait que le miroir ne contient pas. */
export async function addContexteAction(formData: FormData) {
  const profile = String(formData.get("profile") ?? "");
  const subjectRef = String(formData.get("subject_ref") ?? "");
  if (!subjectRef) return;

  const motif = String(formData.get("motif_retard") ?? "").trim();
  const actif = String(formData.get("dossier_toujours_actif") ?? "").trim();
  if (!motif && !actif) return;
  if (actif && !["oui", "non", "incertain"].includes(actif)) return;

  await apiFetch(`/v1/arbitrage/dossier/${encodeURIComponent(subjectRef)}/contexte`, {
    method: "POST",
    body: JSON.stringify({ motif_retard: motif, dossier_toujours_actif: actif }),
    allowForbidden: true,
  });

  if (profile) revalidatePath(`/${profile}/arbitrage`);
}
