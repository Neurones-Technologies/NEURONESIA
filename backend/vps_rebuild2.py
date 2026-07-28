"""Rebuild frontend en arriere-plan sur VPS + monitoring."""
import paramiko, time
from pathlib import Path

from vps_config import REMOTE_DIR, ssh_connect
PROJECT_ROOT = Path(__file__).parent.parent

def run(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return (out + err).strip(), rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)
sftp = client.open_sftp()

# Upload Dockerfile corrige
print("[1] Upload Dockerfile...", flush=True)
with open(PROJECT_ROOT / "frontend" / "Dockerfile", "rb") as f:
    sftp.putfo(f, f"{REMOTE_DIR}/frontend/Dockerfile")
print("    OK", flush=True)

# Lancer le build en arriere-plan
print("[2] Lancement build frontend en arriere-plan...", flush=True)
run(client, f"cd {REMOTE_DIR} && nohup docker compose build frontend > /tmp/frontend_build.log 2>&1 &")
print("    Build lance.", flush=True)

# Attendre et monitorer
print("[3] Monitoring (max 10 min)...", flush=True)
for i in range(60):
    time.sleep(10)
    # Verifier si build en cours
    out, _ = run(client, "pgrep -c -f 'docker compose build' 2>/dev/null || echo 0")
    nb_process = int(out.strip()) if out.strip().isdigit() else 0

    # Dernieres lignes du log
    tail, _ = run(client, "tail -3 /tmp/frontend_build.log 2>/dev/null")
    # Detecter succes ou echec
    success, _ = run(client, "grep -c 'naming to docker.io' /tmp/frontend_build.log 2>/dev/null || echo 0")
    error, _ = run(client, "grep -c 'exit code: 1\\|ERROR\\|failed to solve' /tmp/frontend_build.log 2>/dev/null || echo 0")

    elapsed = (i + 1) * 10
    status = "en cours" if nb_process > 0 else "termine"
    print(f"  t={elapsed}s [{status}] {tail.split(chr(10))[-1][:80]}", flush=True)

    if nb_process == 0:
        # Build termine
        if int(success) > 0:
            print("\n[OK] Build frontend REUSSI!", flush=True)
        elif int(error) > 0:
            print("\n[ERREUR] Build frontend echoue. Log complet:", flush=True)
            log_full, _ = run(client, "cat /tmp/frontend_build.log", timeout=30)
            # Afficher seulement les lignes d'erreur
            for line in log_full.split('\n'):
                if any(k in line for k in ['error', 'ERROR', 'Error', 'failed', 'FAILED']):
                    print(f"  {line}", flush=True)
        break

# Demarrer les services
print("\n[4] Demarrage docker compose up -d...", flush=True)
run(client, f"cd {REMOTE_DIR} && docker compose up -d", timeout=60)
time.sleep(20)

# Etat final
print("\n[5] Etat des conteneurs:", flush=True)
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps")
print(out, flush=True)

print("\n[6] Test health:", flush=True)
health, _ = run(client, "curl -sf http://localhost:8000/health 2>/dev/null || echo 'backend pas pret'")
print(f"  Backend: {health}", flush=True)

frontend_http, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:3001/ 2>/dev/null || echo 'frontend pas pret'")
print(f"  Frontend: {frontend_http}", flush=True)

sftp.close()
client.close()
print("\nScript termine.", flush=True)
