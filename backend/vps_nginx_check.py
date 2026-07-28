"""Inspecte la config nginx et la structure de l'app existante."""
import paramiko

from vps_config import ssh_connect

def run(client, cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    return out + err

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh_connect(client)

sections = [
    ("Nginx sites-available", "ls -la /etc/nginx/sites-available/"),
    ("Nginx sites-enabled", "ls -la /etc/nginx/sites-enabled/"),
    ("Config neurones-cms", "cat /etc/nginx/sites-available/neurones-cms"),
    ("Process node CMS", "ps aux | grep node | grep -v grep"),
    ("neurones-cms package.json", "cat /var/www/neurones-cms/package.json 2>/dev/null | head -20"),
    ("CMS structure", "ls /var/www/neurones-cms/"),
    ("PM2 ou service", "pm2 list 2>/dev/null || systemctl list-units | grep neurones"),
]

for title, cmd in sections:
    print(f"\n{'='*40}")
    print(f"  {title}")
    print(f"{'='*40}")
    result = run(client, cmd)
    print(result.strip() if result.strip() else "(vide)")

client.close()
