import Link from "next/link";
import { apiFetch } from "@/lib/api/client";
import { META } from "@/lib/data/profiles";
import { ROLE_LABELS } from "@/lib/auth/roles";
import { ProfileKey } from "@/lib/types";
import { Acts, Note, Tag, ViewHeader } from "@/components/ui/primitives";

interface Me {
  id: number;
  email: string;
  full_name: string;
  role: string;
  allowed_views: string[] | null;
}

const VIEW_LABELS: Record<string, string> = {
  briefing: "Briefing quotidien",
  dashboard: "Tableau de bord",
  actions: "Actions",
  forecast: "Forecast pondéré",
  tresorerie: "Trésorerie / impayés",
  performance: "Performance & pertes",
  veille: "Veille AO",
  "veille-client": "Veille — vue client",
  "veille-ao": "Veille — vue AO",
  crosssell: "Montée en valeur (cross-sell)",
  portefeuille: "Portefeuille clients",
  presales: "Avant-vente",
  offres: "Offres",
  couts: "Coûts & marges",
  workflow: "Workflow",
  taches: "Tâches",
  leads: "Leads chauds",
  clients: "Clients",
  partenaires: "Fournisseurs / partenaires",
  pipeline: "Pipeline",
  catalogue: "Catalogue",
  documents: "Documents (GED)",
  admin: "Administration",
  arbitrage: "Arbitrages",
};

const ALL_VIEWS = Object.keys(VIEW_LABELS);

export async function ParamsView({ profile }: { profile: ProfileKey }) {
  const meta = META[profile];
  const me = await apiFetch<Me>("/v1/auth/me");
  const isAdmin = me.allowed_views === null;
  const allowed = new Set(me.allowed_views ?? ALL_VIEWS);

  return (
    <>
      <ViewHeader
        eyebrow={`Paramètres · ${meta.name}`}
        title="Périmètre, accès et méthode"
        subtitle="Ce que votre compte peut voir est décidé côté serveur par la matrice module × rôle — pas par cet écran, qui ne fait qu'en afficher le résultat."
      />

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
          <p>Cinq détecteurs réutilisés par plusieurs modules — seuils fixés dans le code, à recalibrer avec l&apos;usage.</p>
        </div>
        <div className="pblk-b">
          <div className="fld">
            <div>
              <div className="fld-n">M1 · Rupture de rythme</div>
              <div className="fld-s">Écart entre le délai depuis le dernier événement et l&apos;intervalle habituel du compte.</div>
            </div>
            <span className="ro">actif</span>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">M2 · Dérive de délai</div>
              <div className="fld-s">Glissement d&apos;un délai réel par rapport à son engagement contractuel.</div>
            </div>
            <span className="ro">actif</span>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">M3 · Écart backlog / facturation</div>
              <div className="fld-s">Courbe de facturation réelle vs théorique du contrat.</div>
            </div>
            <span className="ro">proxy</span>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">M4 · Écart prix achat / vente</div>
              <div className="fld-s">Évolution comparée du prix d&apos;achat et du prix de vente.</div>
            </div>
            <span className="ro">actif</span>
          </div>
          <div className="fld">
            <div>
              <div className="fld-n">M5 · Scoring pipeline</div>
              <div className="fld-s">
                Calibré sur les instantanés quotidiens du pipeline — collecte démarrée aujourd&apos;hui, l&apos;historique
                se construit jour après jour.
              </div>
            </div>
            <Tag variant="w">historique en cours</Tag>
          </div>
          <Note>
            Ces seuils vivent dans le code du backend, pas dans une table éditable — les rendre configurables depuis
            cet écran est un chantier distinct de l&apos;intégration des données.
          </Note>
        </div>
      </div>

      <div className="pblk">
        <div className="pblk-h">
          <h3>Référentiel global</h3>
          <p>Commun aux cinq profils.</p>
        </div>
        <div className="pblk-b">
          <Acts style={{ margin: 0 }}>
            <Link className="btn" href={`/${profile}/referentiel/couverture`}>
              Couverture 29 / 29
            </Link>
            <Link className="btn" href={`/${profile}/referentiel/moteurs`}>
              Moteurs et données
            </Link>
          </Acts>
        </div>
      </div>
    </>
  );
}
