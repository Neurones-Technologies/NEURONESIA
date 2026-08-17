"""
Cree (ou met a jour) les 7 comptes de demonstration du cockpit — un par persona.

Ces comptes se connectent comme n'importe quel autre : POST /v1/auth/login
avec leur email et leur mot de passe (verification bcrypt cote backend).

Idempotent : relancable sans risque. Migre aussi les anciens emails demo
(@neurones-tech.com) vers les nouveaux (@neuronestech.com) sans creer de
doublon.

MOT DE PASSE — fourni par la variable d'environnement DEMO_USERS_PASSWORD,
SANS valeur par defaut : aucun mot de passe n'est ecrit dans le depot, et le
script refuse de tourner si elle est absente. Generer une valeur, par exemple
`openssl rand -base64 24`, puis :

    DEMO_USERS_PASSWORD='<valeur>' python scripts/seed_demo_users.py

Le mot de passe n'est applique qu'a la CREATION des comptes ; pour le
reappliquer aux comptes existants, ajouter --reset-passwords.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from adapters.auth.jwt_adapter import hash_password
from db.database import AsyncSessionLocal, init_db
from db.models import UserModel

_MIN_PASSWORD_LEN = 6  # aligne sur la validation de POST /v1/auth/users


def _read_demo_password() -> str:
    """Lit DEMO_USERS_PASSWORD ou arrete le script avec la marche a suivre."""
    password = os.environ.get("DEMO_USERS_PASSWORD", "")
    if not password:
        sys.exit(
            "DEMO_USERS_PASSWORD absente - aucun mot de passe par defaut n'est "
            "code dans ce depot.\n"
            "Genere une valeur (`openssl rand -base64 24`) puis relance :\n"
            "    DEMO_USERS_PASSWORD='<valeur>' python scripts/seed_demo_users.py"
        )
    if len(password) < _MIN_PASSWORD_LEN:
        sys.exit(
            f"DEMO_USERS_PASSWORD trop courte ({len(password)} caracteres) - "
            f"{_MIN_PASSWORD_LEN} minimum, comme a la creation d'un compte via l'API."
        )
    return password

# Alignes sur frontend/lib/fixtures/profiles.ts (mockup v17)
DEMO_USERS = [
    {"role": "admin", "email": "oboyer@neuronestech.com", "full_name": "Boyer Othniel Nehemie"},
    {"role": "dg", "email": "jmkouadio@neuronestech.com", "full_name": "Direction Generale"},
    {"role": "dir_commercial", "email": "pbourron@neuronestech.com", "full_name": "Direction Commerciale"},
    {"role": "dir_operations", "email": "pyoro@neuronestech.com", "full_name": "Direction des Operations"},
    {"role": "presale", "email": "presales@neuronestech.com", "full_name": "Equipe Avant-Vente"},
    {"role": "dir_financier", "email": "cdjereke@neuronestech.com", "full_name": "Direction Financiere"},
    {"role": "commercial", "email": "sales@neuronestech.com", "full_name": "Commercial"},
]

# Anciens emails demo (seed precedent) -> migres vers le nouvel email du meme role
LEGACY_EMAILS = {
    "dg@neurones-tech.com": "jmkouadio@neuronestech.com",
    "dir.commercial@neurones-tech.com": "pbourron@neuronestech.com",
    "dir.operations@neurones-tech.com": "pyoro@neuronestech.com",
    "presale@neurones-tech.com": "presales@neuronestech.com",
    "dir.financier@neurones-tech.com": "cdjereke@neuronestech.com",
    "commercial@neurones-tech.com": "sales@neuronestech.com",
    # L'ancien compte admin psoro devient le compte dir_operations (meme email)
}


async def main():
    reset_passwords = "--reset-passwords" in sys.argv
    demo_password = _read_demo_password()
    await init_db()
    created, updated = 0, 0

    async with AsyncSessionLocal() as session:
        for spec in DEMO_USERS:
            result = await session.execute(
                select(UserModel).where(UserModel.email == spec["email"])
            )
            user = result.scalar_one_or_none()

            # Migration : un ancien email demo pointe vers ce nouvel email ?
            if not user:
                legacy_email = next(
                    (old for old, new in LEGACY_EMAILS.items() if new == spec["email"]), None
                )
                if legacy_email:
                    result = await session.execute(
                        select(UserModel).where(UserModel.email == legacy_email)
                    )
                    user = result.scalar_one_or_none()
                    if user:
                        print(f"~ migre      : {legacy_email} -> {spec['email']}")
                        user.email = spec["email"]

            if user:
                changed = (
                    user.role != spec["role"]
                    or user.full_name != spec["full_name"]
                    or not user.is_active
                )
                user.role = spec["role"]
                user.full_name = spec["full_name"]
                user.is_active = True
                if reset_passwords:
                    user.hashed_password = hash_password(demo_password)
                    changed = True
                if changed:
                    updated += 1
                    print(f"~ mis a jour : {user.email} -> role {user.role}")
                else:
                    print(f"= inchange   : {user.email} ({user.role})")
            else:
                user = UserModel(
                    email=spec["email"],
                    full_name=spec["full_name"],
                    hashed_password=hash_password(demo_password),
                    role=spec["role"],
                    is_active=True,
                )
                session.add(user)
                created += 1
                print(f"+ cree       : {spec['email']} ({spec['role']})")

        await session.commit()

    print(f"\nOK - {created} cree(s), {updated} mis a jour, {len(DEMO_USERS)} comptes demo au total.")
    # Le mot de passe n'est JAMAIS reaffiche : cette sortie finit dans les logs
    # CI et les historiques de terminal. Il est deja connu de l'appelant, qui
    # l'a fourni via DEMO_USERS_PASSWORD.
    print(
        "Mot de passe : celui de DEMO_USERS_PASSWORD"
        + (
            " (applique a TOUS les comptes)"
            if reset_passwords
            else " (nouveaux comptes uniquement - --reset-passwords pour tous)"
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
