"""
Cree (ou met a jour) les 7 comptes demo du cockpit — un par persona.

Ces comptes alimentent l'ecran de connexion du frontend :
- POST /v1/auth/login (email + mot de passe) — mot de passe demo connu
- POST /v1/auth/demo-login (par role, sans mot de passe, si active)

Idempotent : relancable sans risque. Migre aussi les anciens emails demo
(@neurones-tech.com) vers les nouveaux (@neuronestech.com) sans creer de
doublon.

Mot de passe des comptes demo : variable d'environnement DEMO_USERS_PASSWORD
(defaut "neurones2026"). Applique a la creation ; pour l'appliquer aussi aux
comptes existants : python scripts/seed_demo_users.py --reset-passwords
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from adapters.auth.jwt_adapter import hash_password
from db.database import AsyncSessionLocal, init_db
from db.models import UserModel

DEMO_PASSWORD = os.environ.get("DEMO_USERS_PASSWORD", "neurones2026")

# Alignes sur frontend/lib/fixtures/profiles.ts (mockup v17)
DEMO_USERS = [
    {"role": "admin", "email": "oboyer@neuronestech.com", "full_name": "Boyer Othniel Nehemie"},
    {"role": "dg", "email": "jmkouadio@neuronestech.com", "full_name": "Direction Generale"},
    {"role": "dir_commercial", "email": "pbourron@neuronestech.com", "full_name": "Direction Commerciale"},
    {"role": "dir_operations", "email": "psoro@neuronestech.com", "full_name": "Direction des Operations"},
    {"role": "presale", "email": "presales@neuronestech.com", "full_name": "Equipe Avant-Vente"},
    {"role": "dir_financier", "email": "cdjereke@neuronestech.com", "full_name": "Direction Financiere"},
    {"role": "commercial", "email": "sales@neuronestech.com", "full_name": "Commercial"},
]

# Anciens emails demo (seed precedent) -> migres vers le nouvel email du meme role
LEGACY_EMAILS = {
    "dg@neurones-tech.com": "jmkouadio@neuronestech.com",
    "dir.commercial@neurones-tech.com": "pbourron@neuronestech.com",
    "dir.operations@neurones-tech.com": "psoro@neuronestech.com",
    "presale@neurones-tech.com": "presales@neuronestech.com",
    "dir.financier@neurones-tech.com": "cdjereke@neuronestech.com",
    "commercial@neurones-tech.com": "sales@neuronestech.com",
    # L'ancien compte admin psoro devient le compte dir_operations (meme email)
}


async def main():
    reset_passwords = "--reset-passwords" in sys.argv
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
                    user.hashed_password = hash_password(DEMO_PASSWORD)
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
                    hashed_password=hash_password(DEMO_PASSWORD),
                    role=spec["role"],
                    is_active=True,
                )
                session.add(user)
                created += 1
                print(f"+ cree       : {spec['email']} ({spec['role']})")

        await session.commit()

    print(f"\nOK - {created} cree(s), {updated} mis a jour, {len(DEMO_USERS)} comptes demo au total.")
    print(f"Mot de passe demo : {DEMO_PASSWORD!r}"
          + ("" if reset_passwords else " (nouveaux comptes uniquement — --reset-passwords pour tous)"))


if __name__ == "__main__":
    asyncio.run(main())
