"""Upload docker-compose.yml corrige et redemarrer tous les services."""
import paramiko, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

from vps_config import REMOTE_DIR, ssh_connect
PROJECT_ROOT = Path(__file__).parent.parent

def run(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return (out + err).strip(), rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)
sftp = client.open_sftp()

# Upload docker-compose.yml corrige
print("[1] Upload docker-compose.yml corrige...")
with open(PROJECT_ROOT / "docker-compose.yml", "rb") as f:
    sftp.putfo(f, f"{REMOTE_DIR}/docker-compose.yml")
print("    OK")

# Arreter et relancer tous les services
print("[2] Arret des services existants...")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose down", timeout=30)
print(f"    {out[:100]}")

print("[3] Demarrage de tous les services...")
out, rc = run(client, f"cd {REMOTE_DIR} && docker compose up -d 2>&1", timeout=60)
print(out[:500])
print(f"    exit code: {rc}")

print("[4] Attente 45s demarrage...")
time.sleep(45)

print("[5] Etat des conteneurs:")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps -a")
print(out)

print("[6] Logs backend (20 lignes):")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose logs backend --tail=20 2>/dev/null")
print(out[:2000])

print("[7] Test health:")
health, _ = run(client, "curl -sf http://localhost:8000/health 2>/dev/null || echo 'BACKEND PAS PRET'")
print(f"    Backend: {health}")
frontend_h, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:3001/ 2>/dev/null || echo 'FRONTEND PAS PRET'")
print(f"    Frontend: {frontend_h}")

sftp.close()
client.close()
print("\nTermine!")
