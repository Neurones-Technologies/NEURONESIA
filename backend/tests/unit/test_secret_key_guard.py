"""Garde-fou démarrage : refuse la clé JWT par défaut en environnement non-dev
(sinon tous les tokens sont forgeables avec une valeur publique du code source)."""
import pytest

from config.settings import settings
from main import _DEFAULT_SECRET_KEY, _refuse_insecure_secret_in_prod


def test_refuse_si_prod_et_cle_par_defaut(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", _DEFAULT_SECRET_KEY)
    with pytest.raises(RuntimeError, match="SECRET_KEY par défaut"):
        _refuse_insecure_secret_in_prod()


def test_ok_si_prod_et_cle_personnalisee(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", "une-vraie-cle-openssl-generee")
    _refuse_insecure_secret_in_prod()  # ne lève rien


def test_ok_si_dev_meme_avec_cle_par_defaut(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "secret_key", _DEFAULT_SECRET_KEY)
    _refuse_insecure_secret_in_prod()  # ne lève rien — confort du dev local
