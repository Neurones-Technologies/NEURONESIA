"""
Couche d'extraction structurée (Phase 1 du RAG upgrade).

Transforme un document texte en faits typés, validés (Pydantic) et normalisés
(montants → colonne numérique + devise ; dates → datetime), persistés ensuite
dans la base relationnelle `kb_*`. N'altère pas le pipeline vectoriel existant.
"""
