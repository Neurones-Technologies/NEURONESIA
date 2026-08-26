"""Endpoints d'administration des comptes et des droits (`api/v1/auth.py`).

Ces endpoints existaient sans aucun test. Ce sont pourtant les seuls du projet
qui peuvent, en une requête, retirer l'accès à tout le monde : la protection du
dernier admin actif est la seule chose qui empêche une plateforme définitivement
inadministrable, et rien ne la vérifiait.

Les fonctions de route sont appelées DIRECTEMENT, sans client HTTP — c'est le
style des autres tests unitaires du projet, et cela évite d'avoir à monter
l'application (dont le lifespan branche Odoo et les jobs). Ce qui est perdu au
passage : la résolution des `Depends` et la validation Pydantic des query params.
Les garde-fous testés ici vivent tous dans le corps des fonctions, pas dans leur
signature, donc la couverture reste celle qui compte.

Le tri s'appuie sur `created_at` : les comptes sont donc créés avec des dates
espacées explicitement, `datetime.utcnow()` n'ayant pas la résolution nécessaire
pour distinguer deux insertions consécutives.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.v1 import auth as auth_api
from api.v1 import dependencies as deps
from config.permissions import DEFAULT_MODULE_ACCESS, invalidate_permissions_cache
from core.domain.user import User, UserRole
from db.database import Base
from db.models import AdminAuditModel, ConversationModel, DecisionModel, UserModel


# ── Socle ────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session():
    """Base en mémoire, partagée par toutes les connexions du test.

    `StaticPool` n'est pas un détail de performance : sans lui, chaque connexion
    aiosqlite ouvre sa PROPRE base `:memory:` et les tables créées ici seraient
    invisibles à la requête suivante.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # La matrice effective est mise en cache en mémoire du process (TTL 30 s) :
    # sans purge, un test hérite des surcharges écrites par le précédent.
    invalidate_permissions_cache()
    deps.invalidate_user_cache()
    async with maker() as s:
        yield s
    await engine.dispose()
    invalidate_permissions_cache()


_T0 = datetime(2026, 1, 1, 8, 0, 0)


async def _seed(
    session: AsyncSession,
    email: str,
    role: str = "commercial",
    *,
    is_active: bool = True,
    full_name: str = "",
    last_login: datetime | None = None,
    jours: int = 0,
) -> UserModel:
    user = UserModel(
        email=email,
        full_name=full_name or email.split("@")[0],
        hashed_password="x",  # jamais vérifié ici : aucun test ne passe par /login
        role=role,
        is_active=is_active,
        created_at=_T0 + timedelta(days=jours),
        last_login=last_login,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _acteur(user: UserModel) -> User:
    """Domaine `User` correspondant à un `UserModel` — ce que passent les Depends."""
    return User(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=UserRole(user.role),
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
    )


async def _journal(session: AsyncSession) -> list[AdminAuditModel]:
    result = await session.execute(select(AdminAuditModel).order_by(AdminAuditModel.id))
    return list(result.scalars())


# ── Le contrôle admin ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tous_les_endpoints_admin_refusent_un_non_admin(session):
    """Un seul endpoint oublié suffirait : la liste des comptes, leur fiche et la
    matrice des droits sont autant de fuites que d'écritures."""
    intrus = _acteur(await _seed(session, "dc@nt.ci", role="dir_commercial"))
    cible = await _seed(session, "cible@nt.ci")

    appels = [
        auth_api.list_users(None, None, None, intrus, session),
        auth_api.get_user_detail(cible.id, intrus, session),
        auth_api.list_audit(50, None, intrus, session),
        auth_api.create_user(
            auth_api.CreateUserRequest(email="x@nt.ci", password="secret1"), intrus, session
        ),
        auth_api.update_user(cible.id, auth_api.UpdateUserRequest(full_name="X"), intrus, session),
        auth_api.delete_user(cible.id, intrus, session),
        auth_api.get_permissions(intrus, session),
        auth_api.update_permission(
            auth_api.PermissionUpdateRequest(view="clients", role="commercial", allowed=False),
            intrus,
            session,
        ),
        auth_api.reset_permissions(intrus, session),
    ]
    for appel in appels:
        with pytest.raises(HTTPException) as exc:
            await appel
        assert exc.value.status_code == 403


# ── Création ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creation_normalise_journalise_et_ne_renvoie_jamais_le_hash(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))

    cree = await auth_api.create_user(
        auth_api.CreateUserRequest(
            email="  Nouveau@NT.CI ", password="secret1", full_name=" Ada L ", role="DG"
        ),
        admin,
        session,
    )

    assert cree["email"] == "nouveau@nt.ci"  # minuscules + trim
    assert cree["full_name"] == "Ada L"
    assert cree["role"] == "dg"  # rôle normalisé
    assert cree["is_active"] is True
    assert cree["last_login"] is None
    assert "hashed_password" not in cree and "password" not in cree

    lignes = await _journal(session)
    assert [ligne.action for ligne in lignes] == [auth_api.AUDIT_USER_CREATE]
    assert lignes[0].actor_email == "admin@nt.ci"
    assert lignes[0].target_email == "nouveau@nt.ci"
    assert lignes[0].target_id == cree["id"]  # l'id n'existe qu'après le flush
    assert lignes[0].details == {"role": "dg", "full_name": "Ada L"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("email", "password", "role", "attendu"),
    [
        ("sans-arobase", "secret1", "user", 400),
        ("", "secret1", "user", 400),
        ("ok@nt.ci", "court", "user", 400),
        ("ok@nt.ci", "secret1", "sorcier", 400),
        ("admin@nt.ci", "secret1", "user", 409),  # déjà pris par l'admin du test
    ],
)
async def test_creation_refusee_ne_laisse_aucune_trace(session, email, password, role, attendu):
    """Un refus ne doit rien écrire — ni compte, ni ligne de journal. Sans cette
    vérification, un journal se remplirait de créations qui n'ont pas eu lieu."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))

    with pytest.raises(HTTPException) as exc:
        await auth_api.create_user(
            auth_api.CreateUserRequest(email=email, password=password, role=role), admin, session
        )
    assert exc.value.status_code == attendu
    assert await _journal(session) == []
    total = await session.execute(select(UserModel))
    assert len(list(total.scalars())) == 1  # l'admin, et lui seul


# ── Liste et filtres ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_liste_filtre_sur_le_serveur_et_garde_l_effectif_complet(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin", jours=0))
    await _seed(session, "ada@nt.ci", role="dg", full_name="Ada Lovelace", jours=1)
    await _seed(session, "grace@nt.ci", role="commercial", full_name="Grace H", is_active=False, jours=2)

    tout = await auth_api.list_users(None, None, None, admin, session)
    assert [u["email"] for u in tout["users"]] == ["admin@nt.ci", "ada@nt.ci", "grace@nt.ci"]
    assert tout["total"] == 3
    assert tout["actifs"] == 2
    assert tout["jamais_connectes"] == 3
    assert tout["admins_actifs"] == 1

    # Recherche insensible à la casse, sur l'email ET le nom complet
    assert [u["email"] for u in (await auth_api.list_users("LOVELACE", None, None, admin, session))["users"]] == [
        "ada@nt.ci"
    ]
    assert [u["email"] for u in (await auth_api.list_users("grace@", None, None, admin, session))["users"]] == [
        "grace@nt.ci"
    ]

    par_role = await auth_api.list_users(None, "dg", None, admin, session)
    assert [u["email"] for u in par_role["users"]] == ["ada@nt.ci"]
    # Les compteurs restent ceux de l'effectif complet : filtré, « 1 compte » ne
    # doit pas se lire comme « 1 compte en tout ».
    assert (par_role["total"], par_role["actifs"], par_role["admins_actifs"]) == (3, 2, 1)

    desactives = await auth_api.list_users(None, None, False, admin, session)
    assert [u["email"] for u in desactives["users"]] == ["grace@nt.ci"]
    actifs = await auth_api.list_users(None, None, True, admin, session)
    assert len(actifs["users"]) == 2


@pytest.mark.asyncio
async def test_liste_refuse_un_role_inconnu_plutot_que_de_renvoyer_le_vide(session):
    """Un filtre sur un rôle qui n'existe pas renverrait une liste vide —
    indistinguable d'« aucun compte n'a ce rôle »."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    with pytest.raises(HTTPException) as exc:
        await auth_api.list_users(None, "sorcier", None, admin, session)
    assert exc.value.status_code == 400


# ── Fiche détaillée ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fiche_admin_annonce_un_perimetre_sans_restriction(session):
    admin_model = await _seed(session, "admin@nt.ci", role="admin", last_login=_T0)
    admin = _acteur(admin_model)

    fiche = await auth_api.get_user_detail(admin_model.id, admin, session)

    assert fiche["perimetre"]["is_admin"] is True
    assert fiche["perimetre"]["autorises"] == fiche["perimetre"]["total"] == len(DEFAULT_MODULE_ACCESS)
    assert all(m["allowed"] for m in fiche["perimetre"]["modules"])
    assert fiche["compte"]["est_moi"] is True
    assert fiche["compte"]["jamais_connecte"] is False


@pytest.mark.asyncio
async def test_fiche_lit_le_perimetre_par_la_meme_regle_que_les_endpoints(session):
    """Le périmètre affiché doit venir de `allowed_views`, pas d'une table
    recopiée à côté : c'est la fonction qu'appliquent réellement les endpoints."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    presale = await _seed(session, "presale@nt.ci", role="presale")

    fiche = await auth_api.get_user_detail(presale.id, admin, session)
    autorises = {m["view"] for m in fiche["perimetre"]["modules"] if m["allowed"]}
    attendus = {v for v, acces in DEFAULT_MODULE_ACCESS.items() if acces.get("presale")}

    assert fiche["perimetre"]["is_admin"] is False
    assert autorises == attendus
    assert fiche["perimetre"]["autorises"] == len(attendus)
    assert fiche["compte"]["est_moi"] is False


@pytest.mark.asyncio
async def test_fiche_distingue_le_compte_jamais_connecte(session):
    """Un accès ouvert que personne n'a jamais utilisé n'est pas un compte
    inactif — c'est le signal que l'écran doit pouvoir donner."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    dormant = await _seed(session, "dormant@nt.ci", jours=5)

    fiche = await auth_api.get_user_detail(dormant.id, admin, session)
    assert fiche["compte"]["jamais_connecte"] is True
    assert fiche["compte"]["last_login"] is None
    assert fiche["compte"]["anciennete_jours"] >= 0


@pytest.mark.asyncio
async def test_fiche_compte_les_questions_et_pas_les_reponses(session):
    """`conversations` porte les deux côtés du dialogue. Compter les réponses de
    l'assistant doublerait un chiffre censé décrire l'usage fait du compte."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    dg = await _seed(session, "dg@nt.ci", role="dg")

    session.add_all(
        [
            ConversationModel(session_id="s1", user_id=dg.id, profile="dg", role="user", content="q1", created_at=_T0),
            ConversationModel(session_id="s1", user_id=dg.id, profile="dg", role="assistant", content="r1", created_at=_T0),
            ConversationModel(
                session_id="s2", user_id=dg.id, profile="dc", role="user", content="q2",
                created_at=_T0 + timedelta(days=3),
            ),
            # Question d'un AUTRE compte : ne doit pas être imputée à celui-ci.
            ConversationModel(session_id="s3", user_id=admin.id, profile="dg", role="user", content="q3", created_at=_T0),
        ]
    )
    await session.commit()

    activite = (await auth_api.get_user_detail(dg.id, admin, session))["activite"]
    assert activite["questions_copilote"] == 2
    assert activite["derniere_question"].startswith("2026-01-04")
    assert {p["profile"]: p["questions"] for p in activite["profils"]} == {"dg": 1, "dc": 1}


@pytest.mark.asyncio
async def test_fiche_impute_l_empreinte_par_email(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    dg = await _seed(session, "dg@nt.ci", role="dg")

    session.add_all(
        [
            DecisionModel(title="d1", created_by="dg@nt.ci", status="tranchee", created_at=_T0),
            DecisionModel(
                title="d2", created_by="dg@nt.ci", status="en_cours",
                created_at=_T0 + timedelta(days=2),
            ),
            DecisionModel(title="d3", created_by="autre@nt.ci", status="tranchee", created_at=_T0),
        ]
    )
    await session.commit()

    empreinte = (await auth_api.get_user_detail(dg.id, admin, session))["empreinte"]
    assert empreinte["decisions_creees"] == 2
    assert empreinte["decisions_tranchees"] == 1
    assert empreinte["derniere_decision"].startswith("2026-01-03")


@pytest.mark.asyncio
async def test_fiche_d_un_compte_inconnu_repond_404(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    with pytest.raises(HTTPException) as exc:
        await auth_api.get_user_detail(9999, admin, session)
    assert exc.value.status_code == 404


# ── Modification ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_modification_journalise_le_delta_et_purge_le_cache_de_role(session):
    """Le cache utilisateur (TTL 60 s) garderait l'ancien rôle : un compte
    rétrogradé continuerait d'ouvrir les écrans qu'on vient de lui retirer."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    cible_model = await _seed(session, "cible@nt.ci", role="commercial", full_name="Ancien Nom")
    deps._cache_user(cible_model.id, _acteur(cible_model))

    modifie = await auth_api.update_user(
        cible_model.id,
        auth_api.UpdateUserRequest(role="dg", full_name="Nouveau Nom"),
        admin,
        session,
    )

    assert modifie["role"] == "dg"
    assert deps._get_cached_user(cible_model.id) is None

    lignes = await _journal(session)
    assert [ligne.action for ligne in lignes] == [auth_api.AUDIT_USER_UPDATE]
    assert lignes[0].details == {
        "role": {"avant": "commercial", "apres": "dg"},
        "full_name": {"avant": "Ancien Nom", "apres": "Nouveau Nom"},
    }


@pytest.mark.asyncio
async def test_modification_sans_changement_ne_journalise_rien(session):
    """Un PATCH qui renvoie les mêmes valeurs n'est pas une modification : le
    journal ne doit pas se remplir de lignes qui n'annoncent rien."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    cible = await _seed(session, "cible@nt.ci", role="commercial", full_name="Grace H")

    await auth_api.update_user(
        cible.id,
        auth_api.UpdateUserRequest(full_name="Grace H", role="commercial", is_active=True),
        admin,
        session,
    )
    assert await _journal(session) == []


@pytest.mark.asyncio
async def test_reinitialisation_de_mot_de_passe_tracee_sans_la_valeur(session):
    """Le journal dit QUE le mot de passe a été réinitialisé. Y écrire la valeur,
    même hachée, offrirait une seconde copie du secret à qui lit le journal."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    cible = await _seed(session, "cible@nt.ci")
    avant = cible.hashed_password

    await auth_api.update_user(
        cible.id, auth_api.UpdateUserRequest(password="nouveau-secret"), admin, session
    )

    await session.refresh(cible)
    assert cible.hashed_password != avant
    details = (await _journal(session))[0].details
    assert details == {"password": {"reinitialise": True}}
    assert cible.hashed_password not in str(details)
    assert "nouveau-secret" not in str(details)


@pytest.mark.asyncio
async def test_modification_refuse_un_email_deja_pris_et_ne_touche_a_rien(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    await _seed(session, "pris@nt.ci")
    cible = await _seed(session, "cible@nt.ci", full_name="Intact")

    with pytest.raises(HTTPException) as exc:
        await auth_api.update_user(
            cible.id,
            auth_api.UpdateUserRequest(email="pris@nt.ci", full_name="Écrasé"),
            admin,
            session,
        )
    assert exc.value.status_code == 409

    await session.rollback()
    await session.refresh(cible)
    assert cible.full_name == "Intact"  # rien de partiellement appliqué
    assert await _journal(session) == []


@pytest.mark.asyncio
async def test_modification_d_un_compte_inconnu_repond_404(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    with pytest.raises(HTTPException) as exc:
        await auth_api.update_user(9999, auth_api.UpdateUserRequest(full_name="X"), admin, session)
    assert exc.value.status_code == 404


# ── Le garde-fou qui compte : ne jamais perdre le dernier admin ──────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        auth_api.UpdateUserRequest(role="dg"),
        auth_api.UpdateUserRequest(is_active=False),
    ],
    ids=["retrogradation", "desactivation"],
)
async def test_le_dernier_admin_actif_ne_peut_etre_ni_retrograde_ni_desactive(session, body):
    """Sans ce refus, une seule requête rend la plateforme inadministrable —
    définitivement, puisque plus aucun compte ne peut rouvrir les droits."""
    seul_admin = await _seed(session, "admin@nt.ci", role="admin")
    # Un second admin DÉSACTIVÉ ne compte pas : il ne peut pas administrer.
    await _seed(session, "ex-admin@nt.ci", role="admin", is_active=False)

    with pytest.raises(HTTPException) as exc:
        await auth_api.update_user(seul_admin.id, body, _acteur(seul_admin), session)
    assert exc.value.status_code == 409

    await session.rollback()
    await session.refresh(seul_admin)
    assert seul_admin.role == "admin" and seul_admin.is_active is True


@pytest.mark.asyncio
async def test_le_dernier_admin_actif_ne_peut_pas_etre_supprime(session):
    seul_admin = await _seed(session, "admin@nt.ci", role="admin")
    autre = _acteur(await _seed(session, "admin2@nt.ci", role="admin"))
    # `autre` doit être désactivé pour que `seul_admin` soit bien le dernier actif.
    await auth_api.update_user(autre.id, auth_api.UpdateUserRequest(is_active=False), autre, session)

    with pytest.raises(HTTPException) as exc:
        await auth_api.delete_user(seul_admin.id, autre, session)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_un_admin_peut_etre_retrograde_s_il_en_reste_un_autre(session):
    """Le garde-fou ne doit pas verrouiller le cas légitime : deux admins, l'un
    des deux redevient un utilisateur métier."""
    a = await _seed(session, "a@nt.ci", role="admin")
    b = await _seed(session, "b@nt.ci", role="admin")

    modifie = await auth_api.update_user(
        b.id, auth_api.UpdateUserRequest(role="dg"), _acteur(a), session
    )
    assert modifie["role"] == "dg"


@pytest.mark.asyncio
async def test_on_ne_peut_pas_supprimer_son_propre_compte(session):
    """La désactivation existe pour ça. Se supprimer soi-même laisse une session
    valide sur un compte qui n'existe plus."""
    admin = await _seed(session, "admin@nt.ci", role="admin")
    await _seed(session, "admin2@nt.ci", role="admin")  # pas le dernier admin actif

    with pytest.raises(HTTPException) as exc:
        await auth_api.delete_user(admin.id, _acteur(admin), session)
    assert exc.value.status_code == 409
    assert await _journal(session) == []


# ── Suppression ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_la_trace_de_suppression_survit_au_compte_supprime(session):
    """C'est justement la suppression qu'il faut pouvoir relire : `target_email`
    est une copie, pas une clé étrangère."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    cible = await _seed(session, "cible@nt.ci", role="dg", full_name="Grace H")

    reponse = await auth_api.delete_user(cible.id, admin, session)
    assert reponse == {"deleted": True, "id": cible.id, "email": "cible@nt.ci"}

    reste = await session.execute(select(UserModel).where(UserModel.id == cible.id))
    assert reste.scalar_one_or_none() is None

    lignes = await _journal(session)
    assert [ligne.action for ligne in lignes] == [auth_api.AUDIT_USER_DELETE]
    assert lignes[0].target_email == "cible@nt.ci"
    assert lignes[0].target_id == cible.id
    assert lignes[0].details == {"role": "dg", "full_name": "Grace H", "is_active": True}


@pytest.mark.asyncio
async def test_suppression_d_un_compte_inconnu_repond_404(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    with pytest.raises(HTTPException) as exc:
        await auth_api.delete_user(9999, admin, session)
    assert exc.value.status_code == 404


# ── Matrice module × rôle ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_une_cellule_modifiee_est_journalisee_avec_son_avant_apres(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    avant = DEFAULT_MODULE_ACCESS["forecast"]["commercial"]

    matrice = await auth_api.update_permission(
        auth_api.PermissionUpdateRequest(view="forecast", role="commercial", allowed=not avant),
        admin,
        session,
    )
    assert matrice["matrix"]["forecast"]["commercial"] is (not avant)

    lignes = await _journal(session)
    assert [ligne.action for ligne in lignes] == [auth_api.AUDIT_PERMISSION_UPDATE]
    assert lignes[0].details == {
        "view": "forecast",
        "role": "commercial",
        "avant": avant,
        "apres": not avant,
    }
    assert lignes[0].target_email == ""  # action sur les droits, pas sur un compte


@pytest.mark.asyncio
async def test_les_droits_de_l_admin_ne_sont_pas_modifiables(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    with pytest.raises(HTTPException) as exc:
        await auth_api.update_permission(
            auth_api.PermissionUpdateRequest(view="clients", role="admin", allowed=False),
            admin,
            session,
        )
    assert exc.value.status_code == 400
    assert await _journal(session) == []


@pytest.mark.asyncio
async def test_un_role_ne_peut_pas_perdre_sa_derniere_vue(session):
    """Un rôle sans aucune vue donne des comptes qui se connectent sur rien."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    ouvertes = [v for v, acces in DEFAULT_MODULE_ACCESS.items() if acces.get("presale")]
    assert ouvertes, "le rôle presale doit avoir au moins une vue par défaut"

    for view in ouvertes[:-1]:
        await auth_api.update_permission(
            auth_api.PermissionUpdateRequest(view=view, role="presale", allowed=False),
            admin,
            session,
        )

    with pytest.raises(HTTPException) as exc:
        await auth_api.update_permission(
            auth_api.PermissionUpdateRequest(view=ouvertes[-1], role="presale", allowed=False),
            admin,
            session,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_la_reinitialisation_journalise_le_nombre_de_surcharges_effacees(session):
    """« Matrice réinitialisée » ne décrit pas le même geste sur une table vide
    et sur deux cellules surchargées."""
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    for view in ("forecast", "tresorerie"):
        await auth_api.update_permission(
            auth_api.PermissionUpdateRequest(view=view, role="commercial", allowed=True),
            admin,
            session,
        )

    matrice = await auth_api.reset_permissions(admin, session)
    assert matrice["matrix"] == DEFAULT_MODULE_ACCESS

    lignes = await _journal(session)
    assert lignes[-1].action == auth_api.AUDIT_PERMISSION_RESET
    assert lignes[-1].details == {"surcharges_effacees": 2}


# ── Lecture du journal ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_le_journal_se_lit_du_plus_recent_au_plus_ancien_et_se_filtre(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    cible = await _seed(session, "cible@nt.ci")
    await auth_api.update_user(cible.id, auth_api.UpdateUserRequest(role="dg"), admin, session)
    await auth_api.update_permission(
        auth_api.PermissionUpdateRequest(view="forecast", role="commercial", allowed=True),
        admin,
        session,
    )

    tout = await auth_api.list_audit(50, None, admin, session)
    assert tout["total"] == 2
    assert [ligne["action"] for ligne in tout["lignes"]] == [
        auth_api.AUDIT_PERMISSION_UPDATE,
        auth_api.AUDIT_USER_UPDATE,
    ]

    filtre = await auth_api.list_audit(50, auth_api.AUDIT_USER_UPDATE, admin, session)
    assert [ligne["action"] for ligne in filtre["lignes"]] == [auth_api.AUDIT_USER_UPDATE]
    # `total` reste l'effectif complet du journal, comme pour la liste des comptes.
    assert filtre["total"] == 2

    borne = await auth_api.list_audit(1, None, admin, session)
    assert len(borne["lignes"]) == 1 and borne["total"] == 2


@pytest.mark.asyncio
async def test_la_fiche_ne_montre_que_le_journal_du_compte_affiche(session):
    admin = _acteur(await _seed(session, "admin@nt.ci", role="admin"))
    a = await _seed(session, "a@nt.ci")
    b = await _seed(session, "b@nt.ci")
    await auth_api.update_user(a.id, auth_api.UpdateUserRequest(role="dg"), admin, session)
    await auth_api.update_user(b.id, auth_api.UpdateUserRequest(role="dg"), admin, session)

    fiche = await auth_api.get_user_detail(a.id, admin, session)
    assert [ligne["target_email"] for ligne in fiche["journal"]] == ["a@nt.ci"]
