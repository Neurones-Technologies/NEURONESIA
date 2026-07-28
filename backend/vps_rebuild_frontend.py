"""Upload le Dockerfile corrige et rebuild le frontend sur le VPS."""
import paramiko, time
from pathlib import Path

from vps_config import REMOTE_DIR, ssh_connect
PROJECT_ROOT = Path(__file__).parent.parent

def log(msg): print(f"[deploy] {msg}", flush=True)

def run(client, cmd, timeout=600, check=True):
    log(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    combined = out + err
    if combined.strip():
        print(combined.rstrip())
    if check and rc != 0:
        raise RuntimeError(f"Echec (exit {rc}): {cmd}")
    return combined, rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)
sftp = client.open_sftp()
log("Connecte au VPS.")

# Upload Dockerfile corrige
log("Upload Dockerfile frontend corrige...")
with open(PROJECT_ROOT / "frontend" / "Dockerfile", "rb") as f:
    sftp.putfo(f, f"{REMOTE_DIR}/frontend/Dockerfile")

# Verifier que postinstall.cjs est bien sur le VPS
log("Verification postinstall.cjs sur VPS...")
run(client, f"ls -la {REMOTE_DIR}/frontend/postinstall.cjs", check=False)

# Rebuild frontend
log("Rebuild frontend (5-8 min)...")
run(client,
    f"cd {REMOTE_DIR} && docker compose build frontend 2>&1",
    timeout=600)

# Demarrer les services
log("Demarrage de tous les services...")
run(client, f"cd {REMOTE_DIR} && docker compose up -d", timeout=60)

log("Attente 30s...")
time.sleep(30)

# Etat final
log("Etat des conteneurs :")
run(client, f"cd {REMOTE_DIR} && docker compose ps", timeout=30, check=False)

log("Test backend health :")
run(client, "curl -sf http://localhost:8000/health || echo 'pas encore pret'", timeout=15, check=False)

log("Test frontend :")
run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:3001/ || echo 'pas encore pret'", timeout=15, check=False)

sftp.close()
client.close()
log("Termine!")
