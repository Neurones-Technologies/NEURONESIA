"use server";

import { revalidatePath } from "next/cache";
import type { ArbitrageActionState } from "@/lib/actions/arbitrage-state";
import { ApiError, apiFetch } from "@/lib/api/client";

/** Actions du module Arbitrages.
 *
 * Elles échouaient auparavant en silence : un `return` nu sur motif manquant,
 * un `allowForbidden` qui avalait le 403 de mandat. L'utilisateur cliquait
 * « Journaliser », rien ne se passait, et rien ne disait pourquoi — sur un
 * écran dont la promesse est la traçabilité, c'était le pire endroit possible
 * pour perdre une action. Chaque chemin renvoie désormais une phrase (cf.
 * `ArbitrageActionState`, déclaré hors de ce module : un fichier `"use server"`
 * ne peut exporter que des fonctions asynchrones).
 *
 * Le contrôle de mandat reste celui du serveur (`router._require_mandate`) :
 * ce qui est fait ici ne dispense de rien, cela ne fait qu'éviter d'envoyer une
 * requête dont on sait déjà qu'elle sera refusée. */

function ok(message: string): ArbitrageActionState {
  return { status: "ok", message, at: Date.now() };
}

function ko(message: string, field?: string): ArbitrageActionState {
  return { status: "error", message, field, at: Date.now() };
}

/** Traduit une panne d'appel en phrase affichable. Le `detail` du backend est
 * déjà rédigé pour l'utilisateur (cf. `router._require_mandate`) : on le
 * préfère à un message générique. */
function fromError(error: unknown, fallback: string): ArbitrageActionState {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return ko(error.detail || "Cette action relève d'un autre mandat que le vôtre.");
    }
    return ko(error.detail || fallback);
  }
  return ko(fallback);
}

/** Issues possibles d'un passage en comité. `tranchee` engage, `reportee` et
 * `escaladee` ne tranchent pas mais laissent une trace datée et motivée —
 * l'écran ne proposait auparavant que « journaliser l'option recommandée », si
 * bien qu'un dossier non tranché était indistinguable d'un dossier oublié. */
const STATUTS = ["tranchee", "reportee", "escaladee"] as const;
type Statut = (typeof STATUTS)[number];

const STATUT_CONFIRMATION: Record<Statut, string> = {
  tranchee: "Décision journalisée. Elle est relue dans 30 jours : c'est cette revue qui dira si elle était juste.",
  reportee: "Report journalisé avec son motif. Le dossier reste ouvert et reviendra dans la file.",
  escaladee: "Escalade journalisée avec son motif. Le dossier attend la décision du niveau supérieur.",
};

export async function createDecisionAction(
  _prev: ArbitrageActionState,
  formData: FormData
): Promise<ArbitrageActionState> {
  const profile = String(formData.get("profile") ?? "");
  const statut = String(formData.get("status") ?? "tranchee");
  if (!STATUTS.includes(statut as Statut)) {
    return ko("Issue non reconnue — choisissez trancher, reporter ou escalader.", "status");
  }

  const motif = String(formData.get("motif_decision") ?? "").trim();
  // Même règle que le backend (422 sinon) : un report ou une escalade sans motif
  // ne laisse rien à juger à la revue. On s'arrête ici plutôt que d'envoyer une
  // requête qu'on sait devoir échouer.
  if ((statut === "reportee" || statut === "escaladee") && !motif) {
    return ko(
      statut === "reportee"
        ? "Un report doit dire pourquoi : sans motif, la revue à 30 jours ne peut pas juger si l'attente était fondée."
        : "Une escalade doit dire pourquoi : c'est ce motif que lira le niveau saisi.",
      "motif_decision"
    );
  }

  // Sur un report ou une escalade, aucune option n'est retenue : forcer celle
  // qui était cochée ferait apparaître au registre un engagement jamais pris.
  const optionRetenue = statut === "tranchee" ? String(formData.get("option_retenue") ?? "").trim() : "";
  if (statut === "tranchee" && !optionRetenue) {
    return ko("Sélectionnez l'option retenue avant de trancher.", "option_retenue");
  }

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

  if (!payload.title) return ko("Dossier introuvable — rechargez la page avant de réessayer.");

  try {
    await apiFetch("/v1/arbitrage/decisions", { method: "POST", body: JSON.stringify(payload) });
  } catch (error) {
    return fromError(error, "La décision n'a pas pu être journalisée. Rien n'a été enregistré.");
  }

  if (profile) revalidatePath(`/${profile}/arbitrage`);
  return ok(STATUT_CONFIRMATION[statut as Statut]);
}

/** Verdicts acceptés par le backend (cf. `db/models.py::DecisionModel`). Un verdict
 * hors liste est refusé plutôt que réécrit en « confirme » : un score de fiabilité
 * dont le verdict est imposé ne mesure rien. */
const REVIEW_VERDICTS = ["confirme", "infirme", "partiel"] as const;

export async function markReviewedAction(
  _prev: ArbitrageActionState,
  formData: FormData
): Promise<ArbitrageActionState> {
  const profile = String(formData.get("profile") ?? "");
  const id = formData.get("decision_id");
  if (!id) return ko("Décision introuvable — rechargez la page avant de réessayer.");

  const verdict = String(formData.get("review_verdict") ?? "");
  if (!REVIEW_VERDICTS.includes(verdict as (typeof REVIEW_VERDICTS)[number])) {
    return ko("Choisissez un verdict : la recommandation était-elle confirmée, infirmée ou partiellement juste ?", "review_verdict");
  }

  try {
    await apiFetch(`/v1/arbitrage/decisions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "tranchee",
        // `review_date` n'est PAS réécrite ici : posée à la création, c'est l'échéance
        // de relecture. L'écraser à la date du clic effacerait le fait que la revue a
        // été faite en retard — exactement ce que `revues_en_retard` doit pouvoir dire.
        review_verdict: verdict,
        review_comment: String(formData.get("review_comment") ?? "").trim(),
      }),
    });
  } catch (error) {
    return fromError(error, "La revue n'a pas pu être enregistrée. Rien n'a changé au registre.");
  }

  if (profile) revalidatePath(`/${profile}/arbitrage`);
  return ok("Revue enregistrée. Elle entre dans le taux de confirmation des recommandations.");
}

/** Enregistre les conditions d'entrée en arbitrage activées par un profil.
 *
 * L'écran ne rédige aucune condition : il coche celles du catalogue figé dans le
 * backend (`uc_arbitrage/conditions.py`). Le réglage est attaché au PROFIL, pas
 * à la personne — il vaut donc pour tous les utilisateurs qui portent ce rôle,
 * et le formulaire le dit. Le contrôle reste serveur (`update_conditions`) :
 * chacun règle son profil, l'admin règle n'importe lequel. */
export async function saveConditionsAction(
  _prev: ArbitrageActionState,
  formData: FormData
): Promise<ArbitrageActionState> {
  const profile = String(formData.get("profile") ?? "");
  const profil = String(formData.get("profil") ?? "").trim();
  if (!profil) return ko("Profil introuvable — rechargez la page avant de réessayer.");

  // Cases décochées = absentes du FormData : une sélection vide est donc un
  // enregistrement légitime (retour au socle), pas une erreur de saisie.
  const codes = formData.getAll("codes").map(String).filter(Boolean);

  let retenus = codes.length;
  let total = 0;
  try {
    const reponse = await apiFetch<{ mesure?: { nb_retenus: number; nb_total: number } }>(
      `/v1/arbitrage/conditions/${encodeURIComponent(profil)}`,
      { method: "PUT", body: JSON.stringify({ codes }) }
    );
    retenus = reponse?.mesure?.nb_retenus ?? 0;
    total = reponse?.mesure?.nb_total ?? 0;
  } catch (error) {
    return fromError(error, "Le réglage n'a pas pu être enregistré. Rien n'a changé.");
  }

  if (profile) {
    revalidatePath(`/${profile}/params`);
    revalidatePath(`/${profile}/arbitrage`);
  }
  return ok(
    codes.length === 0
      ? `Réglage enregistré : aucune condition active, la file du profil compte à nouveau ses ${total} dossier(s).`
      : `Réglage enregistré : ${retenus} dossier(s) sur ${total} restent dans la file de ce profil.`
  );
}

/** Dépose la contribution terrain du commercial du compte sur un dossier.
 *
 * Le dossier réclame explicitement le motif du retard en désignant le compte
 * comme responsable de l'information (cf. `aggregation.missing_info`) — sans que
 * rien ne permette de la fournir. C'est la seule action de cet écran ouverte à un
 * profil sans mandat, et c'est voulu : le mandat conditionne le droit d'engager
 * l'entreprise, pas celui d'apporter un fait que le miroir ne contient pas. */
export async function addContexteAction(
  _prev: ArbitrageActionState,
  formData: FormData
): Promise<ArbitrageActionState> {
  const profile = String(formData.get("profile") ?? "");
  const subjectRef = String(formData.get("subject_ref") ?? "");
  if (!subjectRef) return ko("Dossier introuvable — rechargez la page avant de réessayer.");

  const motif = String(formData.get("motif_retard") ?? "").trim();
  const actif = String(formData.get("dossier_toujours_actif") ?? "").trim();
  if (!motif && !actif) {
    return ko("Renseignez au moins le motif du retard ou l'actualité du dossier.", "motif_retard");
  }
  if (actif && !["oui", "non", "incertain"].includes(actif)) {
    return ko("Réponse attendue : oui, non ou incertain.", "dossier_toujours_actif");
  }

  try {
    await apiFetch(`/v1/arbitrage/dossier/${encodeURIComponent(subjectRef)}/contexte`, {
      method: "POST",
      body: JSON.stringify({ motif_retard: motif, dossier_toujours_actif: actif }),
    });
  } catch (error) {
    return fromError(error, "La contribution n'a pas pu être versée au dossier.");
  }

  if (profile) revalidatePath(`/${profile}/arbitrage`);
  return ok("Contribution versée au dossier, datée et signée à votre nom.");
}
