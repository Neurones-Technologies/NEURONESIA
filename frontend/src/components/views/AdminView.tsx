import Link from "next/link";

import { getAudit, getPermissions, getUserDetail, getUsers, type UsersFilters } from "@/lib/api/admin";
import { ProfileKey } from "@/lib/types";
import { Kpi, KpiStrip, ViewHeader } from "@/components/ui/primitives";
import { AuditJournal } from "@/components/views/admin/AuditJournal";
import { adminHref, adminNouveauHref } from "@/components/views/admin/href";
import { Modale } from "@/components/views/admin/Modale";
import { PermissionsMatrix } from "@/components/views/admin/PermissionsMatrix";
import { UserCreateForm } from "@/components/views/admin/UserCreateForm";
import { UserModal } from "@/components/views/admin/UserModal";
import { UsersFiltersBar } from "@/components/views/admin/UsersFiltersBar";
import { UsersTable } from "@/components/views/admin/UsersTable";

/** Écran Comptes — gestion des utilisateurs, des droits par rôle, et journal.
 *
 * Le backend portait déjà tout : création, modification, désactivation,
 * suppression, matrice module × rôle, avec ses garde-fous. Rien n'y donnait
 * accès — la vue Réglages annonçait pourtant « modifiable depuis l'écran
 * Administration », un écran qui n'existait pas. C'est cet écran.
 *
 * Trois blocs, dans l'ordre où l'on s'en sert : l'effectif et sa liste, les
 * droits par rôle, le journal de ce qui a été fait.
 *
 * Les DEUX gestes d'écriture sur un compte — le créer, le modifier — passent par
 * une modale, rendue côté serveur d'après `?nouveau=1` ou `?compte=<id>` (cf.
 * `admin/page.tsx`). Ni l'un ni l'autre n'est posé à côté de la liste : un
 * formulaire permanent sous un tableau laisse croire qu'on peut lire et écrire
 * en même temps, alors qu'écrire ici périme la liste qu'on vient de lire.
 *
 * Ce que cet écran NE dit plus en toutes lettres : chaque bloc portait un
 * paragraphe d'explication. Ils ont été retirés — ils repoussaient les données
 * vers le bas et se relisaient à chaque visite pour n'apprendre qu'une fois. Ce
 * qui subsiste est ce qu'aucune valeur ne montre : que les droits sont attachés
 * au RÔLE et non au compte (la matrice `module_permissions` est indexée sur
 * (view, role) — modifier une case change le périmètre de TOUS les comptes qui
 * portent ce rôle), et que le journal est en ajout seul.
 */
export async function AdminView({
  profile,
  filters,
  selected,
  nouveau,
}: {
  profile: ProfileKey;
  filters: UsersFilters;
  selected?: number;
  nouveau?: boolean;
}) {
  // Un seul aller-retour groupé : la liste, la matrice, le journal et
  // éventuellement la fiche ouverte. Les quatre lectures sont indépendantes.
  const [page, permissions, audit, detail] = await Promise.all([
    getUsers(filters),
    getPermissions(),
    getAudit(30),
    selected !== undefined ? getUserDetail(selected) : Promise.resolve(null),
  ]);

  const desactives = page.total - page.actifs;
  const filtre = filters.q || filters.role || filters.actif !== undefined;

  return (
    <>
      <ViewHeader
        eyebrow="Administration"
        title="Comptes et droits"
        subtitle="Qui peut se connecter, ce que son rôle lui ouvre, et la trace de chaque changement."
      />

      <KpiStrip>
        <Kpi
          label="Comptes"
          value={String(page.total)}
          detail={`${page.actifs} actif(s) · ${desactives} désactivé(s)`}
        />
        <Kpi
          label="Administrateurs actifs"
          value={String(page.admins_actifs)}
          valueVariant={page.admins_actifs === 1 ? "w" : undefined}
          detail={
            page.admins_actifs === 1
              ? "un seul : il ne peut être ni rétrogradé ni désactivé"
              : "chacun peut administrer comptes et droits"
          }
        />
        <Kpi
          label="Jamais connectés"
          value={String(page.jamais_connectes)}
          valueVariant={page.jamais_connectes > 0 ? "w" : "s"}
          detail={
            page.jamais_connectes > 0
              ? "accès ouverts que personne n'a encore utilisés"
              : "tous les comptes ouverts ont servi"
          }
        />
        <Kpi
          label="Modules gérés"
          value={String(permissions.views.length)}
          detail={`droits réglés pour ${permissions.roles.length - 1} rôle(s) métier`}
        />
      </KpiStrip>

      <div className="pblk">
        <div className="pblk-h pblk-h--act">
          <h3>Comptes</h3>
          <Link className="btn btn--p" href={adminNouveauHref(profile, filters)}>
            Nouveau compte
          </Link>
        </div>
        <div className="pblk-b">
          <UsersFiltersBar profile={profile} filters={filters} roles={permissions.roles} />
          <UsersTable
            profile={profile}
            users={page.users}
            filters={filters}
            selected={selected}
          />
          <div className="fld">
            <div className="fld-n">
              {filtre
                ? `${page.users.length} compte(s) affiché(s) sur ${page.total}`
                : `${page.total} compte(s)`}
            </div>
            <span className="ro">{filtre ? "liste filtrée" : "effectif complet"}</span>
          </div>
        </div>
      </div>

      <div className="pblk">
        <div className="pblk-h">
          <h3>Droits par rôle</h3>
          <p>
            Une case = un module ouvert à un rôle, pour TOUS les comptes qui le portent.
          </p>
        </div>
        <div className="pblk-b">
          <PermissionsMatrix profile={profile} permissions={permissions} />
        </div>
      </div>

      <div className="pblk">
        <div className="pblk-h">
          <h3>Journal d&apos;administration</h3>
          <p>En ajout seul : aucun écran ne peut le corriger ni le purger.</p>
        </div>
        <div className="pblk-b">
          <AuditJournal lignes={audit.lignes} total={audit.total} limit={audit.limit} />
        </div>
      </div>

      {/* Un seul panneau à la fois : `?compte=` l'emporte sur `?nouveau=1`, les
          deux ne pouvant se superposer utilement (cf. `admin/page.tsx`, qui
          n'en laisse d'ailleurs passer qu'un). */}
      {selected !== undefined ? (
        <UserModal
          profile={profile}
          detail={detail}
          filters={filters}
          roles={permissions.roles}
          adminsActifs={page.admins_actifs}
        />
      ) : (
        nouveau && (
          <Modale
            eyebrow="Nouveau compte"
            titre="Créer un compte"
            fermer={adminHref(profile, filters, null)}
          >
            <UserCreateForm profile={profile} roles={permissions.roles} />
          </Modale>
        )
      )}
    </>
  );
}
