import type { AuditLine } from "@/lib/api/admin";
import { formatDateTime } from "@/lib/format";
import { actionLabel, auditDetail } from "@/components/views/admin/audit-text";

/** Journal d'administration.
 *
 * Composant serveur, en lecture seule : la table est en ajout seul côté backend,
 * et aucun endpoint ne la modifie ni ne la purge. Rien à rendre interactif ici —
 * un journal qu'on peut corriger depuis l'écran qu'il surveille ne prouve rien.
 */
export function AuditJournal({
  lignes,
  total,
  limit,
}: {
  lignes: AuditLine[];
  total: number;
  limit: number;
}) {
  if (lignes.length === 0) {
    return (
      <p className="arb-empty arb-empty--inline">
        Aucune action enregistrée. Le journal se remplit à la première création, modification ou
        suppression de compte, et à la première modification des droits.
      </p>
    );
  }

  return (
    <>
      <div style={{ overflowX: "auto" }}>
        <table className="tb">
          <thead>
            <tr>
              <th>Quand</th>
              <th>Action</th>
              <th>Compte visé</th>
              <th>Ce qui a changé</th>
              <th>Par</th>
            </tr>
          </thead>
          <tbody>
            {lignes.map((ligne) => (
              <tr key={ligne.id}>
                <td className="mono">{formatDateTime(ligne.at)}</td>
                <td>{actionLabel(ligne.action)}</td>
                <td className="mono">{ligne.target_email || "—"}</td>
                <td>{auditDetail(ligne)}</td>
                <td className="mono">{ligne.actor_email}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="fld">
        <div>
          <div className="fld-n">
            {total > lignes.length
              ? `${lignes.length} action(s) affichée(s), les plus récentes, sur ${total} enregistrée(s)`
              : `${total} action(s) enregistrée(s)`}
          </div>
          <div className="fld-s">
            {total > lignes.length
              ? `L'écran s'arrête aux ${limit} dernières : au-delà, la lecture se fait par l'API (GET /v1/auth/audit?limit=).`
              : "Tout le journal tient à l'écran."}
          </div>
        </div>
        <span className="ro">ajout seul</span>
      </div>
    </>
  );
}
