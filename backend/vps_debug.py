"""Debug du build frontend sur VPS."""
import paramiko, sys

from vps_config import ssh_connect

def run(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out + err

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)

# Voir le log complet du build frontend (erreur npm ci)
print("=== LOG COMPLET (grep npm ci error) ===")
print(run(client, "grep -A 30 'npm ci' /opt/neurones-ia/deploy.log | head -60"))

print("=== Fichiers dans /opt/neurones-ia/frontend/ ===")
print(run(client, "ls -la /opt/neurones-ia/frontend/"))

print("=== package-lock.json present? ===")
print(run(client, "ls -la /opt/neurones-ia/frontend/package*.json"))

print("=== Ollama status ===")
print(run(client, "cd /opt/neurones-ia && docker compose logs ollama --tail=20"))

print("=== Ollama models ===")
print(run(client, "docker exec neurones-ollama ollama list 2>/dev/null || echo 'pas de modele'"))

# Tenter de rebuild frontend manuellement avec output complet
print("=== Rebuild frontend (verbose) ===")
print(run(client,
    "cd /opt/neurones-ia && docker compose build frontend 2>&1 | tail -40",
    timeout=120))

client.close()
