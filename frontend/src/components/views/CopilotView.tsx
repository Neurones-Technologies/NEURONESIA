import { Suspense } from "react";
import { apiFetch } from "@/lib/api/client";
import { META } from "@/lib/data/profiles";
import { ProfileKey } from "@/lib/types";
import { ChatBox } from "@/components/copilot/ChatBox";
import { SessionSummary } from "@/components/copilot/ConversationList";

const SUGGESTED: Record<ProfileKey, { title: string; questions: string[] }[]> = {
  dg: [
    {
      title: "Atterrissage et budget",
      questions: [
        "Où atterrit l'exercice cette année comparé au budget ?",
        "Pourquoi le CA est-il en retard ou en avance sur l'année dernière ?",
      ],
    },
    {
      title: "Portefeuille",
      questions: ["Quels sont mes 10 plus gros clients ?", "Quelle est notre concentration sur le top 5 client ?"],
    },
  ],
  dc: [
    { title: "Forecast", questions: ["Quel est mon pipeline pondéré ce trimestre ?", "Quelles opportunités ont une échéance dépassée ?"] },
    { title: "Développement", questions: ["Quels clients n'ont pas de ligne Cybersécurité ?", "Pourquoi perdons-nous des affaires ?"] },
  ],
  do: [
    { title: "Backlog", questions: ["Quel est mon backlog par dossier ?", "Quels dossiers ont une dérive de marge ?"] },
    { title: "Fournisseurs", questions: ["Quels fournisseurs nous mettent en retard ?", "Où sommes-nous en situation mono-fournisseur ?"] },
  ],
  df: [
    { title: "Encaissement", questions: ["Combien vais-je encaisser dans les 30 prochains jours ?", "Quels sont mes plus gros débiteurs ?"] },
    { title: "Marge", questions: ["Quels dossiers ont la plus grosse marge cette année ?", "Où perdons-nous de la marge ?"] },
  ],
  am: [
    { title: "Préparation", questions: ["Quels sont mes comptes les plus à risque ?", "Prépare ma fiche pour un client précis"] },
    { title: "Développement", questions: ["Quelles opportunités de vente additionnelle sur mon portefeuille ?", "Rédige une relance pour un client"] },
  ],
};

/** Conversations déjà menées depuis ce profil. Chargé côté serveur pour que la
 * sidebar soit peuplée au premier rendu ; le client ne la rafraîchit ensuite
 * qu'après un échange ou une suppression. Une panne de l'historique ne doit pas
 * empêcher de poser une question : on retombe sur une liste vide. */
async function loadSessions(profile: ProfileKey): Promise<SessionSummary[]> {
  try {
    const data = await apiFetch<{ sessions: SessionSummary[] }>(
      `/v1/chat/sessions?profile=${profile}`
    );
    return data.sessions ?? [];
  } catch {
    return [];
  }
}

export async function CopilotView({ profile }: { profile: ProfileKey }) {
  const meta = META[profile];
  const sessions = await loadSessions(profile);
  const groups = SUGGESTED[profile];

  return (
    <>
      <Suspense fallback={null}>
        <ChatBox
          profile={profile}
          initialSessions={sessions}
          placeholder="Posez une question sur vos données…"
          suggested={groups.flatMap((g) => g.questions)}
          avatar={meta.code}
        />
      </Suspense>
    </>
  );
}
