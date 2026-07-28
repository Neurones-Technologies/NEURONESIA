"""Upload docker-compose corrige et redemarrer backend avec bon healthcheck."""
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
print("[1] Upload docker-compose.yml...")
with open(PROJECT_ROOT / "docker-compose.yml", "rb") as f:
    sftp.putfo(f, f"{REMOTE_DIR}/docker-compose.yml")

# Redemarrer juste le backend (pas de rebuild)
print("[2] Redemarrage backend...")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose up -d backend frontend")
print(out[:300])

print("[3] Attente 30s...")
time.sleep(30)

print("[4] Etat:")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps")
print(out)

print("[5] Test /v1/health:")
out, _ = run(client, "curl -sf http://localhost:8000/v1/health || echo 'ECHEC'")
print(f"   Backend /v1/health: {out}")

print("[6] Test frontend:")
out, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:3001/")
print(f"   Frontend: {out}")

print("[7] Test nginx ia.neuronestech.com:")
out, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' -L http://ia.neuronestech.com/ 2>/dev/null || echo 'DNS non resolu'")
print(f"   ia.neuronestech.com: {out}")

print("[8] Nginx config:")
out, _ = run(client, "cat /etc/nginx/sites-enabled/neurones-ia 2>/dev/null || echo 'config absente'")
print(out[:500])

# Lancer le sync Odoo initial
print("\n[9] Lancement sync Odoo initial (en arriere-plan)...")
out, _ = run(client,
    f"cd {REMOTE_DIR} && docker compose exec -T backend python scripts/run_full_sync.py > /tmp/sync.log 2>&1 &",
    timeout=10)
print("   Sync lance en arriere-plan.")

sftp.close()
client.close()
print("\nTermine!")
