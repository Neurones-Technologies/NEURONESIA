"""Exploration initiale du VPS avant déploiement."""
import paramiko
import sys

from vps_config import VPS_HOST as HOST, ssh_connect

def run(client, cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out + err

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)
print("[OK] Connecte au VPS", HOST)

sections = [
    ("OS", "cat /etc/os-release | head -6"),
    ("CPU/RAM", "nproc && free -h | head -3"),
    ("Disques", "df -h"),
    ("Docker", "docker ps -a 2>/dev/null || echo 'docker non installé'"),
    ("Docker Compose", "docker compose version 2>/dev/null || docker-compose version 2>/dev/null || echo 'compose non installé'"),
    ("Ports actifs", "ss -tlnp | grep LISTEN"),
    ("Nginx", "nginx -v 2>&1; ls /etc/nginx/sites-enabled/ 2>/dev/null || echo 'pas de nginx'"),
    ("Apps /var/www", "ls /var/www/ 2>/dev/null || echo 'vide'"),
    ("Apps /home", "ls /home/ 2>/dev/null"),
    ("Crons", "crontab -l 2>/dev/null || echo 'aucun cron'"),
    ("Espace dossiers", "du -sh /var/www/* 2>/dev/null; du -sh /home/* 2>/dev/null; du -sh /opt/* 2>/dev/null"),
]

for title, cmd in sections:
    print(f"\n{'='*40}")
    print(f"  {title}")
    print(f"{'='*40}")
    result = run(client, cmd)
    print(result.strip() if result.strip() else "(vide)")

client.close()
