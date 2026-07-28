"""
Schémas SQL exposés au text-to-SQL (Phase 3).

- KB_TABLES / KB_DDL : couche documentaire structurée (kb_*) → outil
  `interroger_documents`.
- ODOO_TABLES : tables miroir Odoo interrogeables → outil `executer_analyse_sql`
  (liste blanche qui EXCLUT users / token_usage / conversations / quarantine
  / ged_entries — fermeture de la fuite de données identifiée en Phase 3).
"""
from __future__ import annotations

# ── Couche documentaire kb_* ─────────────────────────────────────────────────

KB_TABLES: set[str] = {
    "kb_clients", "kb_personnes", "kb_projets",
    "kb_cv", "kb_cv_experiences", "kb_cv_certifications",
    "kb_ao", "kb_ao_exigences", "kb_ao_references_demandees",
    "kb_compte_rendu", "kb_cr_actions",
    "kb_certification",
    "kb_pv_recette", "kb_pv_reserves",
    "kb_attestation",
    "kb_aliases",
}

KB_DDL = """\
-- Couche documentaire structurée (SQLite, LECTURE SEULE). Montants : colonnes
-- *_valeur (REAL, unités entières) + *_devise (XOF/EUR/USD). Dates : DateTime
-- (utiliser date('now'), strftime('%Y', col)). TOUJOURS sélectionner doc_id et
-- fichier_source pour citer les sources. Jointures inter-documents via les
-- colonnes *_ref_id → kb_projets.id / kb_clients.id / kb_personnes.id.

-- Entités canoniques (pivots du croisement)
kb_clients(id PK, raison_sociale, secteur, pays)
kb_personnes(id PK, nom_complet)
kb_projets(id PK, intitule, client_id->kb_clients.id, secteur, montant_valeur, montant_devise, date_debut, date_fin)

-- CV (tête + enfants). Colonnes communes des têtes : doc_id, fichier_source, page, score_confiance, revue_humaine
kb_cv(doc_id PK, fichier_source, page, score_confiance, nom_complet, titre_poste, annees_experience, localisation, personne_ref_id->kb_personnes.id)
kb_cv_experiences(id PK, doc_id->kb_cv.doc_id, intitule_projet, client, role, secteur, date_debut, date_fin, en_cours, projet_ref_id->kb_projets.id)
kb_cv_certifications(id PK, doc_id->kb_cv.doc_id, intitule, organisme, annee)

-- Appel d'offres
kb_ao(doc_id PK, fichier_source, page, reference, intitule, maitre_ouvrage, date_publication, date_limite_remise, budget_valeur, budget_devise, type_marche, duree_execution, client_ref_id, projet_ref_id)
kb_ao_exigences(id PK, doc_id->kb_ao.doc_id, categorie, libelle, obligatoire)
kb_ao_references_demandees(id PK, doc_id->kb_ao.doc_id, description, nombre_min, montant_min_valeur, montant_min_devise, periode)

-- Compte rendu
kb_compte_rendu(doc_id PK, fichier_source, page, date_reunion, objet, projet_associe, lieu, projet_ref_id)
kb_cr_actions(id PK, doc_id->kb_compte_rendu.doc_id, libelle, responsable, echeance, statut)

-- Certification
kb_certification(doc_id PK, fichier_source, page, titulaire, intitule, organisme_emetteur, numero_identifiant, date_emission, date_expiration, statut, domaine, personne_ref_id)

-- PV de recette
kb_pv_recette(doc_id PK, fichier_source, page, reference, projet_associe, client, date, type_recette, statut_global, projet_ref_id, client_ref_id)
kb_pv_reserves(id PK, doc_id->kb_pv_recette.doc_id, description, criticite, statut, date_levee)

-- Attestation de bonne exécution (table de référence n°1 pour répondre aux AO)
kb_attestation(doc_id PK, fichier_source, page, reference, emetteur_client, projet_marche, montant_valeur, montant_devise, date_debut, date_fin, duree_mois, niveau_appreciation, secteur, client_ref_id, projet_ref_id)

-- Alias d'entités (statut confirmed/auto/pending). Pour des faits fiables :
-- joindre/filtrer status IN ('confirmed','auto').
kb_aliases(id PK, entity_type, alias_norm, alias_raw, entity_id, status, score, source_doc_id)
"""

# ── Tables Odoo interrogeables (sans les tables sensibles) ───────────────────

ODOO_TABLES: set[str] = {
    "clients", "contracts", "invoices", "projects",
    "sale_orders", "purchase_orders", "opportunities", "dossiers",
    "veille_sources", "veille_entries",
}
