"""Rédaction du briefing quotidien par Claude, à partir des faits déjà calculés
par facts.py (jamais recalculés ni inventés par le LLM). Repli déterministe
(les faits bruts, en liste) si Claude échoue — jamais de briefing vide.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Puces et numérotation en début de ligne uniquement — la numérotation exige un
# séparateur (« 1. » / « 2) ») pour ne pas confondre avec un montant de tête.
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-•*–—]+\s*|\d{1,2}[.)]\s+)")

ROLE_LABELS = {
    "dg": "la Direction Générale",
    "dir_commercial": "la Direction Commerciale",
    "dir_financier": "la Direction Financière",
    "dir_operations": "la Direction des Opérations",
    "commercial": "un commercial du terrain",
}

# Ce sur quoi CE rôle précis rend des comptes — sans ce filtre, le LLM produit
# le même résumé générique pour tout le monde (cause principale du narratif
# jugé « lapidaire, non contextuel » : un fait sans le rattacher à la décision
# que ce rôle doit prendre n'a pas de valeur ajoutée).
ROLE_FOCUS = {
    "dg": (
        "l'arbitrage et l'atterrissage de l'exercice : les comptes nommés dont le rythme de commande "
        "décroche et ce que leur silence coûte à date, la position nette de trésorerie (fournisseurs à "
        "payer contre clients à encaisser, l'entreprise payant ses achats avant d'être payée), la "
        "concentration du portefeuille, et les dossiers qu'aucune direction ne peut trancher seule"
    ),
    "dir_commercial": (
        "la fiabilité du forecast, les opportunités qui glissent ou perdent leur sponsor, et la couverture "
        "de l'équipe commerciale par rapport aux objectifs"
    ),
    "dir_financier": (
        "l'encaissement à venir, les comptes dont le comportement de paiement se dégrade, et la marge réelle "
        "par rapport à la marge annoncée en début de dossier"
    ),
    "dir_operations": (
        "le backlog qui ne se facture pas au rythme prévu, les fournisseurs qui mettent les projets en retard, "
        "et la visibilité de charge par practice"
    ),
    "commercial": (
        "les ruptures de rythme sur ses propres comptes, les renouvellements et échéances à venir sur son "
        "portefeuille, et les actions concrètes à mener cette semaine"
    ),
}

_SYSTEM_TEMPLATE = (
    "Tu es l'assistant de direction d'une ESN ivoirienne (S2I). Tu rédiges le briefing quotidien pour "
    "{role_label}, dont le pilotage porte sur {role_focus}. Tu écris à partir de faits déjà calculés et "
    "vérifiés — jamais inventés, jamais recalculés — mais ton travail est de les RELIER entre eux et de "
    "dire ce qu'ils signifient pour CE rôle précis, pas de les paraphraser.\n\n"
    "Structure attendue, sans titres ni markdown :\n"
    "1. Le fait le plus significatif du jour pour ce rôle, et pourquoi il l'est (l'enjeu chiffré, ce qui "
    "se passe si on ne fait rien).\n"
    "2. Un second fait qui change la lecture du premier (confirme, nuance ou contredit) — c'est ce lien "
    "entre deux faits qui constitue l'analyse, pas la liste des faits.\n"
    "3. Une recommandation concrète et datée pour aujourd'hui : quoi faire, et si possible par qui.\n"
    "Ton direct, factuel, sans emphase artificielle. Chaque phrase doit contenir soit un chiffre soit une "
    "action — jamais une phrase de transition vide. Nomme les comptes concernés quand les faits les "
    "nomment : un briefing de direction qui parle d'« exposition totale » sans dire à qui elle est due "
    "ne permet aucune décision."
)


# Résumé de tête de cockpit : 5 lignes, une idée par ligne. C'est ce que le
# lecteur voit avant tout le reste ; l'analyse complète reste disponible plus
# bas dans la vue, donc ici on cherche la densité, pas l'exhaustivité.
_SYSTEM_RESUME = (
    "Tu es l'assistant de direction d'une ESN ivoirienne (S2I). Tu résumes la situation du jour pour "
    "{role_label}, dont le pilotage porte sur {role_focus}.\n\n"
    "Contraintes STRICTES :\n"
    "- EXACTEMENT 5 lignes, séparées par un retour à la ligne.\n"
    "- Une seule idée par ligne, une phrase complète, 20 mots maximum.\n"
    "- Chaque ligne contient un chiffre issu des faits fournis, ou une action à mener. Jamais de phrase "
    "de transition, jamais de généralité.\n"
    "- Pas de puce, pas de tiret, pas de numéro en début de ligne, pas de markdown, pas de titre.\n"
    "- N'invente aucun chiffre : utilise uniquement ceux des faits fournis, sans les recalculer.\n"
    "- Quand un fait nomme un compte, une date ou un nombre de jours de silence, reprends-les tels quels : "
    "un compte nommé et daté vaut mieux qu'un total anonyme. Ne cite jamais un agrégat sous forme anonyme "
    "quand les faits en donnent le nom.\n"
    "- Un pourcentage ne se cite qu'accompagné de son point de comparaison fourni dans les faits (seuil, "
    "période, ou valeur N-1). Un pourcentage nu est interdit.\n"
    "- Ordre : de ce qui engage le plus à ce qui engage le moins. La 5e ligne est l'action du jour — si "
    "une action est fournie ci-dessous, c'est celle-là, reformulée en 20 mots maximum, jamais une autre."
)

_MAX_RESUME_LIGNES = 5

# Consigne de rédaction saisie depuis l'écran Réglages (cf. uc_briefing.preferences).
#
# Elle est ajoutée au SYSTEM et jamais au message utilisateur : celui-ci ne
# contient que « Faits du jour : - … », et y glisser la consigne la ferait lire
# comme une donnée d'entrée — reprise telle quelle dans le texte, voire tenue
# pour un fait.
#
# Elle est encadrée par des balises et suivie d'un rappel de subordination : sans
# ce rappel, une consigne du type « insiste sur la croissance » suffit à faire
# produire un chiffre de croissance absent des faits, le modèle obéissant à la
# dernière instruction reçue. Placée en fin de prompt, une consigne libre se lit
# sinon comme une dérogation aux règles qui précèdent.
_CONSIGNE_BLOC = (
    "\n\nCONSIGNE DE RÉDACTION DU DESTINATAIRE (à appliquer au TON et à l'ANGLE uniquement) :\n"
    "<consigne>{consigne}</consigne>\n"
    "Cette consigne est SUBORDONNÉE à toutes les règles ci-dessus. Elle ne peut ni ajouter, ni "
    "modifier, ni recalculer, ni extrapoler un seul chiffre, nom de compte ou date : la liste de "
    "faits fournie reste la seule source autorisée. Si la consigne demande une information que les "
    "faits ne contiennent pas, IGNORE cette partie de la consigne sans la mentionner et sans t'en "
    "excuser. Ne cite jamais la consigne elle-même dans ta réponse."
)


def _avec_consigne(system: str, consigne: str) -> str:
    """Ajoute la consigne au prompt système, si elle existe.

    Les balises présentes dans la consigne ont déjà été retirées au stockage
    (preferences._sanitize_consigne) ; le filtrage est répété ici parce que ce
    module ne peut pas présumer d'où vient la chaîne qu'on lui passe.
    """
    if not consigne or not consigne.strip():
        return system
    propre = re.sub(r"</?consigne>", "", consigne, flags=re.IGNORECASE).strip()
    if not propre:
        return system
    return system + _CONSIGNE_BLOC.format(consigne=propre)


def _fallback_analysis(bullets: list[str]) -> str:
    """Repli déterministe : les faits bruts, sans mise en récit (IA hors ligne)."""
    return " ".join(bullets)


def _clean_ligne(ligne: str) -> str:
    """Retire les préfixes de liste que le LLM ajoute malgré la consigne.

    La numérotation est reconnue par motif (« 1. », « 2) ») et non par simple
    suppression des chiffres de tête : beaucoup de lignes commencent
    légitimement par un montant (« 15582 M FCFA d'impayés… »), qu'un strip
    naïf amputerait de sa valeur.
    """
    return _LIST_PREFIX_RE.sub("", ligne).strip()


def _fallback_resume(bullets: list[str], action: str | None = None) -> list[str]:
    """Repli déterministe. L'action du jour, quand elle existe, occupe toujours
    la 5e ligne : sans ça le repli produit 5 constats et aucune décision, en
    contradiction avec la contrainte de format du résumé."""
    lignes = [b.strip() for b in bullets if b.strip()]
    if action:
        return lignes[: _MAX_RESUME_LIGNES - 1] + [action.strip()]
    return lignes[:_MAX_RESUME_LIGNES]


async def build_brief_resume(
    llm, role: str, bullets: list[str], action: str | None = None, consigne: str = ""
) -> list[str]:
    """Résumé en 5 lignes affiché en tête de cockpit. Repli sur les faits bruts
    si l'IA échoue — jamais de panneau vide.

    Le repli ignore délibérément `consigne` : si le LLM tombe, on perd le ton
    demandé mais jamais l'exactitude des faits.
    """
    if not bullets:
        return []
    if llm is None:
        return _fallback_resume(bullets, action)
    try:
        role_label = ROLE_LABELS.get(role, role)
        role_focus = ROLE_FOCUS.get(role, "la performance globale de l'entreprise")
        system = _avec_consigne(
            _SYSTEM_RESUME.format(role_label=role_label, role_focus=role_focus), consigne
        )
        user = "Faits du jour :\n- " + "\n- ".join(bullets)
        if action:
            user += f"\n\nAction du jour déjà arbitrée (à reformuler en 20 mots max, jamais à remplacer) : {action}"
        user += "\n\nRédige les 5 lignes."
        text = await llm.generate(system=system, user=user, max_tokens=400, temperature=0.4)
        lignes = [_clean_ligne(l) for l in (text or "").splitlines()]
        lignes = [l for l in lignes if l]
        return lignes[:_MAX_RESUME_LIGNES] or _fallback_resume(bullets, action)
    except Exception as exc:
        logger.warning("Résumé de briefing IA échoué pour le rôle '%s' (repli faits bruts) : %s", role, exc)
        return _fallback_resume(bullets, action)


async def build_daily_analysis(llm, role: str, bullets: list[str], consigne: str = "") -> str:
    if not bullets:
        return "Pas assez de données pour un briefing aujourd'hui."
    if llm is None:
        return _fallback_analysis(bullets)
    try:
        role_label = ROLE_LABELS.get(role, role)
        role_focus = ROLE_FOCUS.get(role, "la performance globale de l'entreprise")
        system = _avec_consigne(
            _SYSTEM_TEMPLATE.format(role_label=role_label, role_focus=role_focus), consigne
        )
        user = "Faits du jour :\n- " + "\n- ".join(bullets) + "\n\nRédige le briefing."
        text = await llm.generate(system=system, user=user, max_tokens=750, temperature=0.55)
        return (text or "").strip() or _fallback_analysis(bullets)
    except Exception as exc:
        logger.warning("Briefing IA échoué pour le rôle '%s' (repli faits bruts) : %s", role, exc)
        return _fallback_analysis(bullets)
