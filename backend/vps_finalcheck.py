"""Verification finale + test endpoints reels."""
import paramiko, time, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

from vps_config import REMOTE_DIR, ssh_connect

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

# Test backend depuis l'hote VPS (pas depuis l'interieur du container)
print("=== Test backend /health depuis hote VPS ===")
out, _ = run(client, "curl -sf http://localhost:8000/health || echo 'ECHEC'")
print(out)

print("\n=== Test backend /v1/stats depuis hote VPS ===")
out, _ = run(client, "curl -sf http://localhost:8000/v1/stats | head -c 300 || echo 'ECHEC'")
print(out)

print("\n=== Etat conteneurs ===")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose ps")
print(out)

print("\n=== Logs backend complets (erreurs eventuelles) ===")
out, _ = run(client, f"cd {REMOTE_DIR} && docker compose logs backend --tail=30 2>/dev/null")
print(out)

print("\n=== Test frontend depuis hote ===")
out, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://localhost:3001/ || echo 'ECHEC'")
print(f"Frontend: {out}")

# Verifier que nginx redirige bien
print("\n=== Test nginx (si DNS ia.neuronestech.com configure) ===")
out, _ = run(client, "curl -sf -o /dev/null -w 'HTTP %{http_code}' http://ia.neuronestech.com/ 2>/dev/null || echo 'DNS pas encore configure'")
print(f"ia.neuronestech.com: {out}")

# Uploader le Dockerfile corrige avec curl
print("\n=== Upload Dockerfile backend corrige (avec curl) ===")
dockerfile_path = Path(__file__).parent / "Dockerfile"
with open(dockerfile_path, "rb") as f:
    content = f.read()
# Ajouter curl dans le dockerfile
content = content.replace(
    b"    gcc \\\n    && rm -rf",
    b"    gcc \\\n    curl \\\n    && rm -rf"
)
sftp.open(f"{REMOTE_DIR}/backend/Dockerfile", "wb").write(content)
print("    Dockerfile corrige uploade (curl ajoute).")
print("    Pour appliquer: docker compose build backend && docker compose up -d backend")

sftp.close()
client.close()
print("\nVerification terminee!")
