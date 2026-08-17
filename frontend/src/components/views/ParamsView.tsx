import { getBriefingPreferences } from "@/lib/api/briefing";
import { getMirrorCoverageSafe } from "@/lib/api/donnees";
import { getMe } from "@/lib/api/me";
import { engineFiability, ENGINES } from "@/lib/data/donnees";
import { profileToRole, ROLE_LABELS } from "@/lib/auth/roles";
import { formatDate } from "@/lib/format";
import { ProfileKey } from "@/lib/types";
import { Note, Tag } from "@/components/ui/primitives";
import { DebriefForm } from "@/components/views/params/DebriefForm";

const VIEW_LABELS: Record<string, string> = {
  briefing: "Briefing quotidien",
  dashboard: "Tableau de bord",
  forecast: "Forecast pondéré",
  tresorerie: "Trésorerie / impayés",
  performance: "Performance & pertes",
  crosssell: "Montée en valeur (cross-sell)",
  portefeuille: "Portefeuille clients",
  couts: "Coûts & marges",
  clients: "Clients",
  partenaires: "Fournisseurs / partenaires",
  arbitrage: "Arbitrages",
};

const ALL_VIEWS = Object.keys(VIEW_LABELS);

/** Vue Réglages — connectée au backend réel : identité et périmètre depuis
 * `/v1/auth/me` (matrice module × rôle appliquée côté serveur, pas un
 * masquage d'écran), fiabilité des moteurs depuis `/v1/stats/mirror`.
 *
 * La règle tenue ici depuis l'origine : aucun bouton sans un état serveur
 * derrière. Les seuils des moteurs restent donc en lecture seule — ils vivent
 * dans le code. La composition du débrief, elle, y satisfait : la table
 * `briefing_preferences` la persiste par rôle, et `PUT /v1/briefing/preferences`
 * l'écrit. C'est la seule section modifiable de cet écran, et ce n'est pas une
 * exception à la règle mais son application. */
export async function ParamsView({ profile }: { profile: ProfileKey }) {
  // Le prop `profile` était ignoré tant que l'écran était en lecture seule. Il
  // devient signifiant : un admin peut ouvrir /dc/params (cf. [profile]/layout)
  // et doit alors régler le débrief DU PROFIL AFFICHÉ, pas le sien. Pour un
  // non-admin, le layout a déjà garanti que ce profil est le sien.
  const roleCible = profileToRole(profile);
  const [me, coverage, prefs] = await Promise.all([
    getMe(),
    getMirrorCoverageSafe(),
    getBriefingPreferences(roleCible),
  ]);
  const isAdmin = me.allowed_views === null;
  const allowed = new Set(me.allowed_views ?? ALL_VIEWS);

  return (
    <>
      <div className="pblk">
        <div className="pblk-h">
          <h3>Compte et périmètre</h3>
          <p>Identité et rôle réels, tels que renvoyés par le serveur d&apos;authentification.</p>
        </div>
        <div className="pblk-b">
          <div className="fld">
            <div>
              <div className="fld-n">Connecté comme</div>
              <div className="fld-s">{me.email}</div>
            </div>
            <span className="ro">{me.full_name}</span>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">Rôle</div>
              <div className="fld-s">{ROLE_LABELS[me.role] ?? me.role}</div>
            </div>
            <Tag variant="s">actif</Tag>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">Connexion précédente</div>
              <div className="fld-s">Horodatage du dernier jeton émis avant celui-ci</div>
            </div>
            <span className="ro">{me.last_login ? formatDate(me.last_login) : "première connexion"}</span>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">Portée d&apos;accès</div>
              <div className="fld-s">
                {isAdmin
                  ? "Administrateur — accès à tous les modules, sans restriction."
                  : `${allowed.size} module(s) autorisé(s) sur ${ALL_VIEWS.length}.`}
              </div>
            </div>
            <span className="ro">lecture seule</span>
          </div>
        </div>
      </div>

      {prefs && (
        <div className="pblk">
          <div className="pblk-h">
            <h3>Personnaliser mon débrief</h3>
            <p>
              Ce que le briefing quotidien de {ROLE_LABELS[roleCible] ?? roleCible} doit contenir. Un
              élément décoché n&apos;est plus calculé du tout — ni sa puce, ni son chiffre. Le résumé de
              tête garde 5 lignes quel que soit le nombre d&apos;éléments : l&apos;analyse complète, elle,
              les reprend tous. Réglage partagé par tous les comptes de ce profil.
            </p>
          </div>
          <div className="pblk-b">
            <DebriefForm
              profile={profile}
              role={prefs.role}
              elements={prefs.elements}
              consigne={prefs.consigne}
              consigneMax={prefs.consigne_max}
              source={prefs.source}
              updatedBy={prefs.updated_by}
            />
          </div>
        </div>
      )}

      <div className="pblk">
        <div className="pblk-h">
          <h3>Disponibilité des modules</h3>
          <p>
            Matrice module × rôle appliquée côté serveur sur chaque endpoint (pas un simple masquage d&apos;écran) —
            modifiable depuis l&apos;écran Administration.
          </p>
        </div>
        <div className="pblk-b">
          <div className="rows">
            {ALL_VIEWS.map((view) => (
              <div className="row" key={view}>
                <div>
                  <div className="row-n">{VIEW_LABELS[view]}</div>
                </div>
                <Tag variant={isAdmin || allowed.has(view) ? "s" : "n"}>
                  {isAdmin || allowed.has(view) ? "disponible" : "non autorisé"}
                </Tag>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="pblk">
        <div className="pblk-h">
          <h3>Moteurs de détection</h3>
          <p>
            Six moteurs réutilisés par plusieurs modules — seuils fixés dans le code, fiabilité de M3/M5 mesurée sur
            l&apos;historique réel des instantanés.
          </p>
        </div>
        <div className="pblk-b">
          {ENGINES.map((e) => {
            const fiab = engineFiability(e, coverage?.tables ?? null);
            return (
              <div className="fld" key={e.code}>
                <div>
                  <div className="fld-n">{e.nom}</div>
                  <div className="fld-s">{e.role}</div>
                </div>
                <Tag variant={fiab.variant}>{fiab.label}</Tag>
              </div>
            );
          })}
          <Note>
            Ces seuils vivent dans le code du backend, pas dans une table éditable — les rendre configurables depuis
            cet écran est un chantier distinct de l&apos;intégration des données.
          </Note>
        </div>
      </div>
    </>
  );
}
