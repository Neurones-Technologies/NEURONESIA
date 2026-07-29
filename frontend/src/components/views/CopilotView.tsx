import { Suspense } from "react";
import { apiFetch } from "@/lib/api/client";
import { META } from "@/lib/data/profiles";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { ProfileKey } from "@/lib/types";
import { Note, ScopeBar, ViewHeader } from "@/components/ui/primitives";
import { ChatBox } from "@/components/copilot/ChatBox";

interface Me {
  email: string;
  full_name: string;
  role: string;
  allowed_views: string[] | null;
}

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

export async function CopilotView({ profile }: { profile: ProfileKey }) {
  const meta = META[profile];
  const me = await apiFetch<Me>("/v1/auth/me");
  const groups = SUGGESTED[profile];

  return (
    <>
      <ViewHeader
        title="Interroger les données"
        subtitle="Le Copilote interroge directement le miroir Odoo avec les mêmes outils que le reste du cockpit (CRM, factures, statistiques) — jamais de donnée inventée."
      />

      <ScopeBar
        items={[
          ["Connecté comme", `${me.full_name} · ${ROLE_LABELS[me.role] ?? me.role}`],
          [
            "Accès",
            me.allowed_views === null ? "Administrateur · accès complet" : `${me.allowed_views.length} module(s) autorisé(s)`,
          ],
        ]}
      />

      <Suspense fallback={null}>
        <ChatBox
          placeholder="Posez une question sur vos données…"
          suggested={groups.flatMap((g) => g.questions)}
          avatar={meta.code}
        />
      </Suspense>

      <Note accent style={{ marginTop: 20 }}>
        Le Copilote répond à partir des mêmes tables que le reste du cockpit. Si une donnée n&apos;est pas dans le
        miroir (feuilles de temps, échanges clients, marge sur prestation), il le signale plutôt que d&apos;estimer.
      </Note>
    </>
  );
}
