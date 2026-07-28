"""Config partagée par les scripts d'administration VPS (vps_*.py, deploy_vps*.py).

Authentification par clé SSH par défaut (cohérent avec le Host "iavps" de
~/.ssh/config → ~/.ssh/id_ed25519) : aucun secret nécessaire dans ce dépôt.
VPS_PASS reste supporté en repli (backend/.env.vps, gitignored) si la clé
est indisponible, mais ne doit plus être la voie normale.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env.vps")

VPS_HOST = os.environ.get("VPS_HOST", "76.13.51.87")
VPS_USER = os.environ.get("VPS_USER", "root")
VPS_KEY_FILE = os.environ.get("VPS_KEY_FILE", str(Path.home() / ".ssh" / "id_ed25519"))
VPS_KEY_PASSPHRASE = os.environ.get("VPS_KEY_PASSPHRASE")  # uniquement si la clé est protégée
VPS_PASS = os.environ.get("VPS_PASS")  # repli déconseillé si aucune clé n'est disponible
REMOTE_DIR = os.environ.get("VPS_REMOTE_DIR", "/opt/neurones-ia")

_HAS_KEY = Path(VPS_KEY_FILE).exists()

if not _HAS_KEY and not VPS_PASS:
    sys.exit(
        f"Aucune authentification disponible : clé SSH introuvable ({VPS_KEY_FILE}) "
        "et VPS_PASS non défini. Renseigne VPS_KEY_FILE dans backend/.env.vps si ta clé "
        "est ailleurs, ou VPS_PASS en dernier recours (voir .env.vps.example)."
    )


def ssh_connect(client, timeout=15):
    """Connecte au VPS : clé SSH si disponible (voie normale), sinon mot de passe."""
    if _HAS_KEY:
        client.connect(
            VPS_HOST, username=VPS_USER, key_filename=VPS_KEY_FILE,
            passphrase=VPS_KEY_PASSPHRASE, timeout=timeout,
        )
    else:
        client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=timeout)
