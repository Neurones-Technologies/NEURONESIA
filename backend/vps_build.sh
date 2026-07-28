#!/bin/bash
# Script de build exécuté directement sur le VPS
set -e

DEPLOY_DIR="/opt/neurones-ia"
LOG="/opt/neurones-ia/deploy.log"

echo "[$(date)] Démarrage du build..." | tee -a $LOG

cd $DEPLOY_DIR

# Build backend
echo "[$(date)] Build backend (5-10 min)..." | tee -a $LOG
docker compose build backend 2>&1 | tee -a $LOG

# Build frontend
echo "[$(date)] Build frontend (3-5 min)..." | tee -a $LOG
docker compose build frontend 2>&1 | tee -a $LOG

# Démarrer tous les services
echo "[$(date)] Démarrage services..." | tee -a $LOG
docker compose up -d 2>&1 | tee -a $LOG

echo "[$(date)] Attente 30s..." | tee -a $LOG
sleep 30

echo "[$(date)] Etat des conteneurs :" | tee -a $LOG
docker compose ps 2>&1 | tee -a $LOG

echo "[$(date)] Test health backend..." | tee -a $LOG
curl -sf http://localhost:8000/health && echo "backend OK" || echo "backend pas encore pret"

echo "[$(date)] Build terminé avec succès!" | tee -a $LOG
