"""Verification etat complet VPS + debug frontend build."""
import paramiko, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from vps_config import REMOTE_DIR, ssh_connect

def run(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return (out + err).strip(), rc

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)

# Etat des conteneurs
print("=== docker compose ps ===")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps -a")
print(out)

# Images disponibles
print("\n=== Images Docker ===")
out, _ = run(client, "docker images | grep neurones")
print(out)

# Log du build frontend
print("\n=== Log build frontend (tail 30) ===")
out, _ = run(client, "tail -30 /tmp/frontend_build.log 2>/dev/null || echo 'log absent'")
print(out)

# Verifier si frontend image existe
print("\n=== Image frontend existe? ===")
out, _ = run(client, "docker inspect neurones-ia-frontend:latest 2>/dev/null | grep -c 'Id' || echo '0'")
print(f"neurones-ia-frontend image count: {out}")

# Logs backend si existe
print("\n=== Logs backend (derniere erreur) ===")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose logs backend --tail=20 2>/dev/null || echo 'pas de logs backend'")
print(out)

# Essayer docker compose up directement
print("\n=== docker compose up -d ===")
out, rc = run(client, f"cd {REMOTE_DIR} && docker compose up -d 2>&1", timeout=60)
print(out)
print(f"exit code: {rc}")

import time; time.sleep(15)

print("\n=== Etat final ===")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps -a")
print(out)

client.close()
