"""
Crée le premier utilisateur admin dans la base de données.
Usage : python scripts/create_admin.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from adapters.auth.jwt_adapter import hash_password
from db.database import AsyncSessionLocal, init_db
from db.models import UserModel


async def main():
    print("=== Création du compte admin Neurones IA ===\n")

    email = input("Email admin : ").strip()
    if not email:
        print("Email requis.")
        return

    full_name = input("Nom complet : ").strip()

    import getpass
    password = getpass.getpass("Mot de passe : ")
    confirm = getpass.getpass("Confirmer le mot de passe : ")

    if password != confirm:
        print("Les mots de passe ne correspondent pas.")
        return
    if len(password) < 8:
        print("Le mot de passe doit faire au moins 8 caractères.")
        return

    await init_db()

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(UserModel).where(UserModel.email == email.lower())
        )
        if existing.scalar_one_or_none():
            print(f"\nUn utilisateur avec l'email '{email}' existe déjà.")
            return

        admin = UserModel(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hash_password(password),
            role="admin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        await session.refresh(admin)
        print(f"\n✓ Admin créé avec succès : {admin.email} (id={admin.id})")
        print("  Vous pouvez maintenant vous connecter sur http://localhost:3000/login")


if __name__ == "__main__":
    asyncio.run(main())
