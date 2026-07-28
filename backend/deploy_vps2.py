"""
Script de déploiement — Phase 2 : upload du script de build + exécution sur le VPS.
Le build Docker tourne côté serveur (pas de timeout SSH).
"""
import paramiko
import io
import time
from pathlib import Path

from vps_config import VPS_HOST, REMOTE_DIR, ssh_connect
PROJECT_ROOT = Path(__file__).parent.parent


def log(msg):
    print(f"[deploy] {msg}", flush=True)


def ssh_run(client, cmd, timeout=120, check=True):
    log(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
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


def stream_build_log(client, log_path: str, poll_interval: int = 10, max_wait: int = 1800):
    """Suit le fichier de log du build avec tail -f simulé."""
    log(f"Suivi du build en cours (max {max_wait//60} min)...")
    last_line = 0
    elapsed = 0
    while elapsed < max_wait:
        out, _, rc = ssh_run(client,
            f"wc -l < {log_path} 2>/dev/null || echo 0",
            timeout=10, check=False)
        try:
            current_line = int(out.strip())
        except ValueError:
            current_line = 0

        if current_line > last_line:
            # Afficher les nouvelles lignes
            out2, _, _ = ssh_run(client,
                f"sed -n '{last_line+1},{current_line}p' {log_path}",
                timeout=10, check=False)
            if out2.strip():
                print(out2.rstrip())
            last_line = current_line

        # Vérifier si le build est terminé
        out3, _, rc3 = ssh_run(client,
            f"grep -c 'Build terminé\\|erreur\\|Error\\|FAILED' {log_path} 2>/dev/null || echo 0",
            timeout=10, check=False)
        done_count = int(out3.strip()) if out3.strip().isdigit() else 0
        if done_count > 0:
            break

        # Vérifier si le process de build est encore en cours
        out4, _, _ = ssh_run(client,
            f"pgrep -f 'docker compose build' | wc -l",
            timeout=10, check=False)
        if out4.strip() == "0" and elapsed > 60:
            log("Process de build terminé.")
            break

        time.sleep(poll_interval)
        elapsed += poll_interval
        log(f"  ... build en cours ({elapsed}s / {max_wait}s)")

    # Afficher les dernières lignes restantes
    out, _, _ = ssh_run(client, f"tail -20 {log_path}", timeout=10, check=False)
    print(out.rstrip())


def main():
    log(f"Connexion SSH à {VPS_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_connect(client, timeout=20)
    sftp = client.open_sftp()
    log("Connecté.")

    # ─── Uploader le script de build ──────────────────────────────────────
    script_path = Path(__file__).parent / "vps_build.sh"
    with open(script_path, "rb") as f:
        sftp.putfo(f, f"{REMOTE_DIR}/build.sh")
    ssh_run(client, f"chmod +x {REMOTE_DIR}/build.sh")

    # ─── Lancer le build en arrière-plan ──────────────────────────────────
    log("Lancement du build Docker en arrière-plan sur le VPS...")
    ssh_run(client,
        f"nohup bash {REMOTE_DIR}/build.sh > {REMOTE_DIR}/deploy.log 2>&1 &",
        timeout=10, check=False)

    log("Build lancé. Suivi du log...")
    time.sleep(5)

    # ─── Suivre le log ────────────────────────────────────────────────────
    stream_build_log(client, f"{REMOTE_DIR}/deploy.log")

    # ─── Vérification finale ──────────────────────────────────────────────
    log("\n=== État final ===")
    ssh_run(client, f"cd {REMOTE_DIR} && docker compose ps", timeout=30, check=False)
    ssh_run(client, "curl -sf http://localhost:8000/health || echo 'backend pas encore pret'",
            timeout=15, check=False)

    sftp.close()
    client.close()

    log("\nDéploiement terminé!")
    log(f"Frontend : http://ia.neuronestech.com (après DNS) ou http://{VPS_HOST}:3001")
    log(f"Backend  : http://ia.neuronestech.com/api/v1 ou http://{VPS_HOST}:8000/v1")
    log("\nPROCHAINES ÉTAPES :")
    log(f"1. Pointer ia.neuronestech.com → {VPS_HOST} dans votre DNS")
    log(f"2. ssh root@{VPS_HOST}")
    log("   cd /opt/neurones-ia")
    log("   docker compose exec backend python scripts/run_full_sync.py")
    log("   docker compose exec backend python scripts/initial_ingest.py")


if __name__ == "__main__":
    main()
