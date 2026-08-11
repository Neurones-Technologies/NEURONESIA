"""Parties rédigées du dossier d'arbitrage — les seules confiées au LLM.

Répartition stricte, identique au reste du projet (cf.
uc_forecast/decision_client.py, uc10_presales) : Python calcule et décide,
Claude rédige. Concrètement ici :

  aggregation.py  →  positions, enjeu, les trois options, l'option recommandée
  payeur.py       →  profil de payeur, échéancier (nb d'échéances, montants, horizon)
  narratif.py     →  la formulation de l'échéancier en langage de comité,
                     et l'avocat du contraire

Aucun montant, aucune date, aucun choix d'option ne sort du modèle : tout ce
qu'il reçoit est déjà arrêté, et les replis déterministes couvrent l'appel
indisponible comme la réponse mal formée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from modules.uc_arbitrage import narration_store

logger = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

_SYSTEM = (
    "Tu es « avocat du contraire » dans un comité de direction d'ESN ivoirienne. "
    "On te donne une décision recommandée et les chiffres réels qui la motivent. "
    "Ton rôle est d'argumenter CONTRE cette recommandation, en français, de façon "
    "concise et factuelle — jamais d'inventer de chiffre absent du contexte fourni."
)

_USER_TEMPLATE = """Dossier : {subject_label}
Enjeu commercial : {enjeu_m} M FCFA
Impayé constaté : {impaye_m} M FCFA
Comportement de paiement mesuré du client : {payeur_lecture}
Option recommandée : {option_titre} — {option_description}
{memoire}
Réponds STRICTEMENT en JSON, sans texte autour :
{{"raisons": ["raison 1 en une phrase", "raison 2 en une phrase"]}}"""

# Rédaction de l'option C. Le modèle reçoit un échéancier DÉJÀ calculé et n'a le
# droit d'en changer aucun chiffre : il le formule comme une proposition
# présentable au client. C'est exactement la valeur attendue de lui — traduire un
# calcul en argument de négociation — et rien de plus.
_SYSTEM_ECHEANCIER = (
    "Tu es directeur financier d'une ESN ivoirienne (S2I). On te donne un plan "
    "d'apurement DÉJÀ CALCULÉ à partir du comportement de paiement réel du client. "
    "Tu le reformules en français, en une proposition courte et négociable à présenter "
    "au client. Tu ne dois JAMAIS modifier un montant, un nombre d'échéances ou un "
    "délai, ni en inventer d'autres : ces chiffres sont arrêtés."
)

_USER_ECHEANCIER = """Client : {client}
Impayé total échu : {impaye_m} M FCFA
Plan calculé (à ne pas modifier) : {nb} échéances de {tranche_m} M FCFA, une tous les {pas} jours, sur {horizon} jours au total.
Ce plan est calibré sur le délai de paiement réellement observé chez ce client : {delai} jours.
Contrepartie commerciale : {declencheur}
Enjeu commercial débloqué : {enjeu_m} M FCFA

Réponds STRICTEMENT en JSON, sans texte autour :
{{"titre": "titre de l'option en moins de 12 mots", "argumentaire": "2 phrases maximum, ce qu'on dit au client pour qu'il accepte ce plan"}}"""


def _clean_json(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        nl = raw.find("\n")
        raw = raw[nl + 1:] if nl != -1 else raw[3:]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    return _TRAILING_COMMA_RE.sub(r"\1", raw).strip()


def _m(xof: float) -> int:
    return round((xof or 0) / 1_000_000)


def _format_memoire(decisions_passees: list[dict] | None) -> str:
    """Décisions déjà prises sur ce client, avec le verdict de leur revue.

    L'écran promettait que « la relecture recalibre les recommandations
    suivantes » sans que rien ne le fasse : le verdict était stocké puis ignoré.
    L'injecter ici est le chemin le plus court pour que la promesse soit tenue —
    l'avocat du contraire peut enfin objecter « cette option a déjà été infirmée
    sur ce client », ce qu'aucun calcul ne pouvait produire.
    """
    if not decisions_passees:
        return ""
    lignes = []
    for d in decisions_passees[:5]:
        verdict = d.get("review_verdict") or ""
        etat = {
            "confirme": "revue : la recommandation s'était vérifiée",
            "infirme": "revue : la recommandation s'était révélée FAUSSE",
            "partiel": "revue : recommandation partiellement vérifiée",
        }.get(verdict, "pas encore revue")
        option = d.get("option_retenue") or "option non renseignée"
        lignes.append(f"- {option} ({etat})")
    return (
        "Décisions déjà prises sur ce même client (à prendre en compte) :\n"
        + "\n".join(lignes)
        + "\n"
    )


def _fallback_raisons(dossier: dict, option: dict) -> list[str]:
    """Repli déterministe — adossé au profil de payeur quand il est mesuré, pour
    que l'objection reste pertinente même sans appel au modèle."""
    enjeu_m = _m(dossier["enjeu_xof"])
    profil = dossier.get("profil_payeur") or {}
    classe = profil.get("classe")

    if classe in ("stable_lent", "stable_rapide", "stable"):
        return [
            f"Ce client règle habituellement à {profil.get('delai_habituel_jours')} j sans que son rythme "
            "ait bougé : traiter ce retard comme une défaillance revient à sanctionner un comportement "
            "connu depuis le début de la relation.",
            f"Bloquer l'engagement fait courir un risque réel sur les {enjeu_m} M FCFA alors que "
            f"{profil.get('taux_recouvrement_pct')} % des factures de ce client finissent encaissées.",
        ]
    if classe == "amelioration":
        return [
            f"Le délai de règlement s'est amélioré ({profil.get('delai_ancien_jours')} j → "
            f"{profil.get('delai_recent_jours')} j) : la dynamique est favorable, un blocage la casserait.",
            f"Les {enjeu_m} M FCFA seraient mis en risque au moment précis où le client redresse son comportement.",
        ]
    if classe in ("degradation", "vigilance"):
        return [
            f"Le ralentissement ({profil.get('delai_ancien_jours')} j → {profil.get('delai_recent_jours')} j) "
            "peut venir d'un changement d'interlocuteur ou d'un litige ponctuel, pas nécessairement d'une "
            "difficulté de paiement — le miroir ne les distingue pas.",
            f"Une réponse trop dure coûte les {enjeu_m} M FCFA chez un client qui a payé "
            f"{profil.get('nb_factures_payees')} factures sans incident jusqu'ici.",
        ]
    if classe == "paiements_stoppes":
        return [
            "L'arrêt des encaissements peut refléter un blocage administratif de notre côté (facture "
            "contestée, pièce manquante, changement de circuit) autant qu'une difficulté du client.",
            f"Bloquer les {enjeu_m} M FCFA sans avoir appelé le client fait porter la décision sur une "
            f"absence de donnée : le miroir constate le silence, il ne l'explique pas.",
        ]
    return [
        f"Bloquer l'engagement commercial fait courir un risque réel de perdre les {enjeu_m} M FCFA au profit d'un concurrent pendant la négociation du recouvrement.",
        "Le motif réel du retard de paiement n'est pas connu du miroir — un client par ailleurs solvable ne doit pas être traité comme un mauvais payeur sans vérification.",
    ]


async def build_counter_argument(
    llm, dossier: dict, option: dict, decisions_passees: list[dict] | None = None
) -> dict:
    """Renvoie `{"raisons", "redige_par"}` — `redige_par` valant "ia" ou "repli",
    comme `write_echeancier`. Le drapeau sert à ne jamais mettre en cache un
    repli déterministe (cf. `build_dossier_narration`) : sans lui, une
    indisponibilité passagère du modèle figeait le repli pour toute la fenêtre."""
    fallback = {"raisons": _fallback_raisons(dossier, option), "redige_par": "repli"}
    if llm is None:
        return fallback
    try:
        profil = dossier.get("profil_payeur") or {}
        user = _USER_TEMPLATE.format(
            subject_label=dossier["subject_label"],
            enjeu_m=_m(dossier["enjeu_xof"]),
            impaye_m=_m(dossier.get("impaye_xof")),
            payeur_lecture=profil.get("lecture", "non mesuré"),
            option_titre=option["titre"],
            option_description=option["description"],
            memoire=_format_memoire(decisions_passees),
        )
        raw = await llm.generate(system=_SYSTEM, user=user, max_tokens=450, temperature=0.3)
        data = json.loads(_clean_json(raw))
        raisons = [str(r).strip() for r in data.get("raisons", []) if str(r).strip()]
        if not raisons:
            return fallback
        return {"raisons": raisons, "redige_par": "ia"}
    except Exception as exc:
        logger.warning("Avocat du contraire IA échoué (repli déterministe) : %s", exc)
        return fallback


async def write_echeancier(llm, dossier: dict, plan: dict) -> dict:
    """Formulation négociable de l'option C. Renvoie
    `{"titre", "argumentaire", "redige_par"}` — `redige_par` valant "ia" ou
    "repli", pour que l'écran puisse dire lequel des deux il affiche plutôt que
    de laisser croire à une rédaction du modèle quand l'appel a échoué.

    Le titre du modèle n'est retenu que s'il est court : un titre à rallonge
    casse la mise en page des cartes d'option, et le titre déterministe
    d'`aggregation.build_options` fait le travail dans ce cas.
    """
    # Le délai cité doit être celui qui a SERVI au calcul (`delai_reference_jours`,
    # c'est-à-dire le rythme récent quand il est mesuré), pas la moyenne de tout
    # l'historique : chez BICICI les deux valent 36 j et 20 j, et afficher 20 j sous
    # un plan calibré sur 36 j donne un argumentaire que le client peut réfuter
    # avec nos propres chiffres.
    delai = plan.get("delai_reference_jours") or (dossier.get("profil_payeur") or {}).get("delai_habituel_jours")
    fallback = {
        "titre": "",
        "argumentaire": (
            f"Le plan reprend le rythme de règlement déjà constaté chez ce client "
            f"({delai} j) : {plan['nb_echeances']} échéances de {_m(plan['tranche_xof'])} M FCFA "
            f"sur {plan['horizon_jours']} j, avec reprise des engagements commerciaux dès la première encaissée."
        ),
        "redige_par": "repli",
    }
    if llm is None:
        return fallback
    try:
        user = _USER_ECHEANCIER.format(
            client=dossier["subject_ref"],
            impaye_m=_m(dossier["impaye_xof"]),
            nb=plan["nb_echeances"],
            tranche_m=_m(plan["tranche_xof"]),
            pas=plan["pas_jours"],
            horizon=plan["horizon_jours"],
            delai=delai,
            declencheur=plan["declencheur"],
            enjeu_m=_m(dossier["enjeu_xof"]),
        )
        raw = await llm.generate(system=_SYSTEM_ECHEANCIER, user=user, max_tokens=400, temperature=0.3)
        data = json.loads(_clean_json(raw))
        argumentaire = str(data.get("argumentaire", "")).strip()
        titre = str(data.get("titre", "")).strip()
        if not argumentaire:
            return fallback
        return {
            "titre": titre if 0 < len(titre) <= 90 else "",
            "argumentaire": argumentaire,
            "redige_par": "ia",
        }
    except Exception as exc:
        logger.warning("Rédaction de l'échéancier IA échouée (repli déterministe) : %s", exc)
        return fallback


def _empreinte(dossier: dict, option: dict, decisions_passees: list[dict] | None, plan: dict | None) -> tuple:
    """Tout ce que les deux prompts consomment réellement, et rien d'autre.

    C'est la clé de cache : elle doit bouger dès qu'un chiffre cité change (une
    sync qui déplace l'impayé, une décision revue qui alimente la mémoire) et
    rester stable sinon. Bâtie sur les champs lus par les gabarits plutôt que sur
    le dossier entier, qui contient des clés sans effet sur la rédaction.

    Depuis le passage en base (`narration_store`), c'est la SEULE mécanique
    d'invalidation : il n'y a plus de TTL derrière pour rattraper une empreinte
    trop large. Y ajouter un champ que les gabarits ne lisent pas ferait
    réécrire la narration pour rien ; en omettre un qu'ils lisent la ferait
    citer des chiffres périmés — sans expiration pour l'effacer.
    """
    profil = dossier.get("profil_payeur") or {}
    # Mêmes 5 décisions que `_format_memoire`, réduites aux deux champs qu'elle lit.
    memoire = tuple(
        (d.get("option_retenue") or "", d.get("review_verdict") or "")
        for d in (decisions_passees or [])[:5]
    )
    # Champs du plan cités dans `_USER_ECHEANCIER`, énumérés un par un plutôt que
    # `plan.items()` : la clé reste juste si `payeur.echeancier` gagne un champ
    # non cité, et ne casse pas s'il en gagne un non hachable.
    echeancier = tuple(
        plan.get(champ) for champ in (
            "nb_echeances", "tranche_xof", "pas_jours", "horizon_jours",
            "delai_reference_jours", "declencheur",
        )
    ) if plan else None
    return (
        "arbitrage_narration",
        dossier["subject_ref"],
        dossier["subject_label"],
        _m(dossier["enjeu_xof"]),
        _m(dossier.get("impaye_xof")),
        profil.get("lecture"),
        profil.get("delai_habituel_jours"),
        option["code"],
        option["titre"],
        option["description"],
        memoire,
        echeancier,
    )


async def build_dossier_narration(
    llm,
    dossier: dict,
    option: dict,
    decisions_passees: list[dict] | None,
    plan: dict | None,
) -> tuple[list[str], dict | None]:
    """Les deux parties rédigées d'un dossier : `(raisons_du_contre, redaction_c)`.

    `redaction_c` vaut None quand le dossier n'a pas d'échéancier calculable (il
    n'y a alors pas d'option C à formuler).

    Les deux appels partent ENSEMBLE : ils ne se lisent pas l'un l'autre, et les
    enchaîner ajoutait la latence du second à celle du premier — c'est ce qui
    dominait le temps d'ouverture d'un dossier.

    Le résultat n'est enregistré que si le modèle a effectivement répondu pour
    les deux parties attendues. Mettre un repli déterministe en base
    reviendrait à faire durer une panne de quelques secondes jusqu'à ce qu'un
    chiffre du dossier change, alors que le repli n'a de sens que le temps de
    l'incident.

    La persistance elle-même est dans `narration_store` (table
    `arbitrage_narrations`) : le cache mémoire ne survivait ni au redéploiement
    ni au second worker uvicorn, et chaque worker repayait ~5 s d'appel modèle.
    """
    async def _rediger() -> tuple[dict, bool]:
        taches = [build_counter_argument(llm, dossier, option, decisions_passees)]
        if plan:
            taches.append(write_echeancier(llm, dossier, plan))
        resultats = await asyncio.gather(*taches)

        contre = resultats[0]
        redaction = resultats[1] if plan else None
        tout_redige = contre["redige_par"] == "ia" and (
            redaction is None or redaction["redige_par"] == "ia"
        )
        return {"raisons": contre["raisons"], "redaction": redaction}, tout_redige

    payload = await narration_store.cached_narration(
        _empreinte(dossier, option, decisions_passees, plan),
        dossier["subject_ref"],
        _rediger,
    )
    # Copies : le payload peut venir de la base comme d'un calcul, l'appelant le
    # modifie (le router pose `titre`/`argumentaire` sur l'option C).
    redaction = payload.get("redaction")
    return list(payload.get("raisons") or []), (dict(redaction) if redaction else None)
