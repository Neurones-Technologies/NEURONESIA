"""
Liste les comptes de la plateforme et, au besoin, reinitialise un mot de passe.

    python scripts/list_users.py
    python scripts/list_users.py --reset-password dtraore@neuronestech.com

Le mot de passe n'est jamais passe en argument (il resterait dans l'historique
du shell et dans la liste des process) ni code dans le script : il est demande
interactivement, sans echo, et confirme. Le hash est produit par la meme
fonction que l'API (adapters/auth/jwt_adapter.hash_password, bcrypt).

La base visee est celle de la configuration (LOCAL_DB_PATH / config/settings.py),
pas un chemin fige — un chemin en dur pointait vers une ancienne installation.
"""
import argparse
import asyncio
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from adapters.auth.jwt_adapter import hash_password
from config.settings import settings
from db.database import AsyncSessionLocal, init_db
from db.models import UserModel

_MIN_PASSWORD_LEN = 6  # aligne sur la validation de POST /v1/auth/users


def _prompt_new_password(email: str) -> str:
    """Demande le nouveau mot de passe deux fois, sans l'afficher."""
    first = getpass.getpass(f"Nouveau mot de passe pour {email} : ")
    if len(first) < _MIN_PASSWORD_LEN:
        sys.exit(f"Mot de passe trop court - {_MIN_PASSWORD_LEN} caracteres minimum.")
    if first != getpass.getpass("Confirmer : "):
        sys.exit("Les deux saisies different - aucune modification.")
    return first


async def _list_users() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserModel).order_by(UserModel.created_at))
        users = result.scalars().all()

    if not users:
        print("Aucun compte en base. Voir scripts/seed_demo_users.py.")
        return

    print(f"{len(users)} compte(s) - base {settings.local_db_path}\n")
    for u in users:
        etat = "actif" if u.is_active else "DESACTIVE"
        derniere = u.last_login.isoformat(timespec="seconds") if u.last_login else "jamais"
        print(f"  {u.id:>3}  {u.email:<40} {u.role:<16} {etat:<10} connexion : {derniere}")


async def _reset_password(email: str) -> None:
    email = email.lower().strip()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserModel).where(UserModel.email == email))
        user = result.scalar_one_or_none()
        if not user:
            sys.exit(f"Aucun compte pour {email} - `python scripts/list_users.py` pour la liste.")

        # La saisie se fait APRES avoir trouve le compte : inutile de faire
        # taper un mot de passe pour un email inexistant.
        user.hashed_password = hash_password(_prompt_new_password(email))
        await session.commit()

    print(f"Mot de passe mis a jour pour {email}.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-password",
        metavar="EMAIL",
        help="reinitialise le mot de passe de ce compte (saisie interactive)",
    )
    args = parser.parse_args()

    await init_db()
    if args.reset_password:
        await _reset_password(args.reset_password)
    else:
        await _list_users()


if __name__ == "__main__":
    asyncio.run(main())
