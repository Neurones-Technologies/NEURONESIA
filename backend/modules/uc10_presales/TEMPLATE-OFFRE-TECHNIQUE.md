# Template — Offre Technique (UC10 Presales)

> Spécification du template d'offre technique Neurones Technologies et du contrat
> qui lie ce template au générateur [`offer_generator.py`](./offer_generator.py).
>
> ⚠️ **Important** : le template **réellement utilisé en production est un `.docx`**,
> pas ce Markdown. Ce document décrit *la structure attendue* de ce `.docx` et les
> règles que le générateur applique. Toute modification du `.docx` doit rester
> cohérente avec les ancres et contraintes ci-dessous, sinon le remplissage échoue
> silencieusement (sections laissées vides ou retombant sur le texte générique).

---

## 1. Emplacement du template `.docx`

Le générateur cherche le `.docx` dans la GED, par domaine :

```
data/ged/offres-techniques/TEMPLATE/{domaine}/*.docx
data/ged/offres-techniques/TEMPLATE/*.docx        # fallback
```

Domaines détectés automatiquement (`_detect_domain`) :
`Digitalisation` (défaut) · `Infrastructure` · `Cybersécurité` · `Cloud`.

Le premier `.docx` trouvé dans le dossier du domaine est utilisé.

---

## 2. Zones variables (remplies) vs zones préservées

| Zone | Action du générateur |
|------|----------------------|
| Noms legacy (`BGFI`, `KORAZ`, `SOCOPRIM`…) | Remplacés par le nom du client partout |
| Page de garde (titre, date, client) | Mise à jour des text boxes / paragraphes |
| En-têtes (`header*.xml`) | Titre projet mis à jour |
| EXPRESSION DES BESOINS | Vidée puis réécrite (3 §) |
| OBJECTIFS DE NEURONES TECHNOLOGIES | Vidée puis réécrite (3 §) |
| PRESENTATION DE LA REPONSE… | Vidée puis réécrite (3 §) |
| Description détaillée de la solution | Vidée puis réécrite (fonctionnalités + modules) |
| TABLE 0 — composants techniques | Mise à jour en place (lignes 1–5) |
| TABLE 1 — équipe | Lignes de données reconstruites |
| TABLE dernière — planning | J/H mis à jour en place + TOTAL |
| **Présentation Neurones** | **Préservée** |
| **Méthodologie de travail** | **Préservée** |
| **Gestion de projet** | **Préservée** |
| **Certifications** | **Préservée** |

---

## 3. Ancres de titres (headings) — À NE PAS MODIFIER

Le générateur localise chaque section par le **texte de son heading** (comparaison
normalisée : casse, accents, apostrophes et tirets ignorés). Ces libellés doivent
exister, dans cet ordre, comme paragraphes de style `Heading *` :

1. `EXPRESSION DES BESOINS`
2. `OBJECTIFS DE NEURONES TECHNOLOGIES`
3. `PRESENTATION DE LA REPONSE DE NEURONES TECHNOLOGIES`
4. `Description détaillée de la solution proposée`
   *(fallback accepté : un heading contenant « Fonctionnalités de l… »)*
5. `MÉTHODOLOGIE DE TRAVAIL ET DESCRIPTION DES SERVICES`
   *(borne de fin de la section « Description détaillée » — préservée)*

> Le contenu situé **entre** deux ancres est intégralement supprimé puis régénéré.
> Renommer ou supprimer une ancre = section non remplie.

---

## 4. Structure de la page de garde

- **Titre du projet** : dans une text box (cas KORAZ) ou un paragraphe normal du
  corps (cas MCI CARE). Détecté par mots-clés legacy ; remplacé en respectant la
  casse (MAJUSCULES conservées).
- **Date** : `Mois Année` (ex. `Avril 2026`), mise à jour à la date du jour.
  Détecte mois FR/EN + année `20xx`.
- **Nom du client** : substitué partout où apparaît un nom legacy.

---

## 5. Les 3 tableaux (ordre = position dans le `.docx`)

### TABLE 0 — Composants / prérequis techniques
- 1 ligne d'en-tête (préservée) + **lignes 1 à 5** = la stack technique.
- Colonnes logiques utilisées : **première** (`composant`) et **dernière** (`version`).
- Le `gridSpan`/merge existant est préservé (mise à jour en place du texte).
- Si moins de 5 composants fournis → lignes restantes vidées.

### TABLE 1 — Équipe projet
- 1 ligne d'en-tête (préservée) ; les lignes de données sont **reconstruites**.
- 2 colonnes attendues : **Rôle/Profil**, **Mission**.
- Si des CV sont matchés dans le scoring → 1 ligne Chef de projet + 1 ligne par CV (max 4).
- Sinon, équipe par défaut (Chef de projet, Expert senior, Développeur, QA).

### TABLE dernière — Planning (J/H)
- Lignes « phase » = cellules fusionnées sur toute la largeur (détectées via `gridSpan`).
- Lignes « activité » = J/H écrit dans la **dernière colonne**.
- Ligne `TOTAL` = somme automatique des J/H numériques.
- **Noms de phases obligatoires** (doivent correspondre EXACTEMENT aux lignes du tableau) :

  ```
  PREALABLE
  PLANIFICATION
  CADRAGE
  IMPLEMENTATION
  FORMATION
  VALIDATION DE LA RECETTE ET PERIODE D'OBSERVATION
  GESTION DE PROJET
  ```

---

## 6. Contrat JSON produit par le LLM

`_generate_sections` demande au LLM un JSON strict qui alimente les zones variables :

```jsonc
{
  "titre_projet": "6–12 mots, commence par un verbe d'action",
  "expression_besoins":  ["§1", "§2", "§3"],        // exactement 3
  "objectifs_reponse":   ["§1", "§2", "§3"],        // exactement 3
  "presentation_reponse":["§1", "§2", "§3"],        // exactement 3
  "fonctionnalites":     ["...", "..."],            // 5 à 8
  "modules": [                                       // 4 à 8
    { "titre": "MODULE 1 — …", "description": "3–4 phrases" }
  ],
  "stack_technique": [                               // 4 à 8
    { "composant": "…", "version": "…" }
  ],
  "planning": [                                      // 7 phases (cf. §5)
    { "phase": "PREALABLE", "activite": "…", "jh": "" }
  ]
}
```

Chaque clé absente/invalide retombe sur un **fallback** générique (voir
`_generate_sections`). En cas de troncature LLM (`OutputTruncatedError`), un parse
de récupération est tenté sur le texte partiel ; `max_tokens = 6000`.

---

## 7. Pièges connus / règles à respecter

- **Ne pas renommer les ancres** du §3 ni les **phases** du §5 — la correspondance
  est textuelle (après normalisation).
- Le `.docx` template doit contenir des **noms legacy** détectables (`KORAZ`,
  `BGFI`…) sur la page de garde et dans les en-têtes, sinon titre/client/date ne
  sont pas remplacés.
- Conserver la **structure de fusion** des tableaux (en-têtes pleine largeur,
  colonne J/H à droite) : le générateur s'appuie dessus.
- L'ordre des tableaux dans le document compte : composants = 1er, équipe = 2e,
  planning = dernier.

---

## 8. Référence code

| Élément | Emplacement |
|---------|-------------|
| Génération complète | `OfferGenerator.generate` |
| Appel LLM + fallbacks | `OfferGenerator._generate_sections` |
| Remplissage `.docx` | `OfferGenerator._fill_template` |
| Détection domaine | `_detect_domain` |
| Recherche template | `_find_template` |
| Tables (composants / équipe / planning) | `_update_tech_table` · `_update_team_table` · `_update_planning_table` |

Voir [`offer_generator.py`](./offer_generator.py) et [`schemas.py`](./schemas.py).
