"""
Garde-fou de fidélité PDF → Markdown (POC parsing GED).

Logique pure, sans dépendance aux libs de parsing : le passage en Markdown ne doit
JAMAIS perdre de contenu en silence. On compare le nombre de caractères alphanumériques
(insensible aux symboles Markdown ajoutés #, |, -, *) entre le Markdown produit et un
texte plat de référence.
"""

FIDELITY_MIN_RATIO = 0.80    # le Markdown doit conserver ≥ 80 % du texte de référence
FIDELITY_MIN_BASELINE = 200  # en-dessous, référence trop courte pour juger (ex. PDF scanné)


def alnum_count(text: str) -> int:
    """Nombre de caractères alphanumériques — métrique de contenu robuste aux symboles Markdown."""
    return sum(1 for ch in text if ch.isalnum())


def is_faithful(markdown: str, baseline: str, min_ratio: float = FIDELITY_MIN_RATIO) -> bool:
    """
    True si le Markdown conserve assez de contenu vs le texte plat de référence.
    Si la référence est trop courte (PDF scanné/illisible), on ne bloque pas sur la
    fidélité : la validation qualité absolue (QualityValidator) reste le garde-fou.
    """
    base = alnum_count(baseline)
    if base < FIDELITY_MIN_BASELINE:
        return True
    return alnum_count(markdown) >= min_ratio * base
