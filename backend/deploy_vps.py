"""
Script de déploiement complet Neurones IA → VPS Hostinger
Usage : python deploy_vps.py [--skip-build] [--skip-data]
"""
import paramiko
import paramiko.sftp_client
import os
import sys
import tarfile
import io
import argparse
import subprocess
from pathlib import Path

from vps_config import VPS_HOST, REMOTE_DIR, ssh_connect

PROJECT_ROOT = Path(__file__).parent.parent  # D:/Neurones-IA/

# Fichiers/dossiers à exclure de l'archive
EXCLUDES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules",
    ".next", ".git", "*.pyc", "*.pyo",
    "data",           # données locales — montées via volume
    ".env",           # jamais committer
    "vps_*.py", "run_resync.py", "check_*.py", "fetch_*.py",
    "resync_*.py", "test_complet.py",
}


def log(msg):
    print(f"[deploy] {msg}", flush=True)


def ssh_run(client, cmd, check=True):
    log(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=120)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        print(out.rstrip())
    if err.strip() and exit_code != 0:
        print(f"STDERR: {err.rstrip()}")
    if check and exit_code != 0:
        raise RuntimeError(f"Commande échouée (exit {exit_code}): {cmd}")
    return out, err, exit_code


def should_exclude(path: Path) -> bool:
    for exc in EXCLUDES:
        if exc.startswith("*"):
            if path.name.endswith(exc[1:]):
                return True
        elif path.name == exc or exc in str(path):
            return True
    return False


def create_archive(source_dir: Path, prefix: str) -> bytes:
    """Crée une archive tar en mémoire d'un sous-dossier."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in source_dir.rglob("*"):
            rel = item.relative_to(source_dir)
            if should_exclude(item) or should_exclude(rel):
                continue
            arcname = f"{prefix}/{rel}"
            tar.add(item, arcname=arcname)
    buf.seek(0)
    return buf.read()


def upload_bytes(sftp, data: bytes, remote_path: str):
    with sftp.open(remote_path, "wb") as f:
        f.write(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true", help="Ne pas rebuild les images Docker")
    parser.add_argument("--skip-data", action="store_true", help="Ne pas transférer la DB SQLite")
    args = parser.parse_args()

    log(f"Connexion SSH à {VPS_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_connect(client, timeout=20)
    sftp = client.open_sftp()
    log("Connecte.")

    # ─── 1. Créer les dossiers sur le VPS ──────────────────────────────────
    log("Creation des dossiers...")
    dirs = [
        REMOTE_DIR,
        f"{REMOTE_DIR}/data/ged",
        f"{REMOTE_DIR}/data/chromadb",
        f"{REMOTE_DIR}/data/bm25_index",
        f"{REMOTE_DIR}/data/local_db",
        f"{REMOTE_DIR}/data/uploads",
        f"{REMOTE_DIR}/data/templates",
        f"{REMOTE_DIR}/ollama_models",
    ]
    for d in dirs:
        ssh_run(client, f"mkdir -p {d}", check=False)

    # ─── 2. Uploader backend ───────────────────────────────────────────────
    log("Archivage et upload du backend...")
    backend_archive = create_archive(PROJECT_ROOT / "backend", "backend")
    upload_bytes(sftp, backend_archive, f"{REMOTE_DIR}/backend.tar.gz")
    ssh_run(client, f"cd {REMOTE_DIR} && tar xzf backend.tar.gz && rm backend.tar.gz")
    log(f"Backend transfere ({len(backend_archive)//1024} KB)")

    # ─── 3. Uploader frontend ──────────────────────────────────────────────
    log("Archivage et upload du frontend...")
    frontend_archive = create_archive(PROJECT_ROOT / "frontend", "frontend")
    upload_bytes(sftp, frontend_archive, f"{REMOTE_DIR}/frontend.tar.gz")
    ssh_run(client, f"cd {REMOTE_DIR} && tar xzf frontend.tar.gz && rm frontend.tar.gz")
    log(f"Frontend transfere ({len(frontend_archive)//1024} KB)")

    # ─── 4. Uploader docker-compose.yml et nginx config ───────────────────
    log("Upload docker-compose.yml et nginx config...")
    for local, remote in [
        (PROJECT_ROOT / "docker-compose.yml", f"{REMOTE_DIR}/docker-compose.yml"),
        (PROJECT_ROOT / "nginx.neurones-ia.conf", f"/etc/nginx/sites-available/neurones-ia"),
    ]:
        with open(local, "rb") as f:
            sftp.putfo(f, remote)
    log("Fichiers de config uploades.")

    # ─── 5. Uploader .env.prod → .env.prod sur le serveur ─────────────────
    env_file = PROJECT_ROOT / ".env.prod"
    if env_file.exists():
        with open(env_file, "rb") as f:
            sftp.putfo(f, f"{REMOTE_DIR}/.env.prod")
        log(".env.prod uploade — PENSEZ a remplir les cles API !")
    else:
        log("ATTENTION: .env.prod absent — a creer manuellement sur le VPS")

    # ─── 6. Uploader les templates Word ───────────────────────────────────
    templates_dir = PROJECT_ROOT / "data" / "templates"
    if templates_dir.exists():
        log("Upload des templates Word...")
        for f in templates_dir.glob("*.docx"):
            with open(f, "rb") as fp:
                sftp.putfo(fp, f"{REMOTE_DIR}/data/templates/{f.name}")
        log("Templates uploades.")

    # ─── 7. Copier la DB SQLite locale → VPS ──────────────────────────────
    if not args.skip_data:
        local_db = PROJECT_ROOT / "data" / "local_db" / "neurones.db"
        if local_db.exists():
            log(f"Upload neurones.db ({local_db.stat().st_size//1024//1024} MB)...")
            with open(local_db, "rb") as f:
                sftp.putfo(f, f"{REMOTE_DIR}/data/local_db/neurones.db")
            log("Base SQLite transferee.")
        else:
            log("DB SQLite absente — sera creee au premier demarrage")

    # ─── 8. Activer nginx ─────────────────────────────────────────────────
    log("Configuration Nginx...")
    ssh_run(client, "ln -sf /etc/nginx/sites-available/neurones-ia /etc/nginx/sites-enabled/neurones-ia", check=False)
    out, _, rc = ssh_run(client, "nginx -t", check=False)
    if rc == 0:
        ssh_run(client, "systemctl reload nginx")
        log("Nginx recharge.")
    else:
        log("ERREUR nginx -t — verifier la config manuellement")

    # ─── 9. Pull du modèle Ollama (si pas encore fait) ────────────────────
    log("Demarrage Ollama et pull du modele llama3.2:3b...")
    ssh_run(client, f"cd {REMOTE_DIR} && docker compose pull ollama 2>/dev/null || true", check=False)
    ssh_run(client, f"cd {REMOTE_DIR} && docker compose up -d ollama")
    log("Attente 10s que Ollama demarre...")
    ssh_run(client, "sleep 10")
    # Pull le modele (si pas encore present)
    ssh_run(client,
            f"cd {REMOTE_DIR} && docker compose exec ollama ollama pull llama3.2:3b",
            check=False)
    log("Modele llama3.2:3b pret (ou deja present).")

    # ─── 10. Build et démarrage des containers ────────────────────────────
    if not args.skip_build:
        log("Build Docker backend (peut prendre 5-10 min)...")
        ssh_run(client, f"cd {REMOTE_DIR} && docker compose build backend")
        log("Build Docker frontend (peut prendre 5-10 min)...")
        ssh_run(client, f"cd {REMOTE_DIR} && docker compose build frontend")

    log("Demarrage de tous les services...")
    ssh_run(client, f"cd {REMOTE_DIR} && docker compose up -d")

    # ─── 11. Vérification ─────────────────────────────────────────────────
    log("Attente 30s pour le demarrage...")
    ssh_run(client, "sleep 30")
    out, _, rc = ssh_run(client, f"cd {REMOTE_DIR} && docker compose ps", check=False)
    log("\nEtat des conteneurs:")
    print(out)

    out, _, _ = ssh_run(client, "curl -sf http://localhost:8000/health || echo 'backend pas encore pret'", check=False)
    log(f"Health backend: {out.strip()}")

    out, _, _ = ssh_run(client, "curl -sf -o /dev/null -w '%{http_code}' http://localhost:3001/ || echo 'frontend pas encore pret'", check=False)
    log(f"Health frontend HTTP: {out.strip()}")

    sftp.close()
    client.close()
    log("\nDeploiement termine!")
    log(f"Application disponible sur: http://ia.neuronestech.com")
    log(f"(Configurez le DNS: ia.neuronestech.com → {VPS_HOST})")
    log("\nPROCHAINES ETAPES:")
    log("1. Editer {REMOTE_DIR}/.env.prod → remplir les cles API")
    log("2. docker compose restart backend")
    log("3. docker compose exec backend python scripts/run_full_sync.py")
    log("4. docker compose exec backend python scripts/initial_ingest.py")


if __name__ == "__main__":
    main()
