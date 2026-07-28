import sqlite3
import bcrypt

new_password = "1234"
hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(12)).decode()

conn = sqlite3.connect("D:/Neurones-IA/data/local_db/neurones.db")
cur = conn.cursor()
cur.execute("UPDATE users SET hashed_password = ? WHERE email = ?", (hashed, "dtraore@neuronestech.com"))
conn.commit()
print(f"Mot de passe mis à jour pour dtraore@neuronestech.com ({cur.rowcount} ligne modifiée)")
conn.close()
