"""Amorçage de `sale_order_lines` depuis le JSON `sale_orders.order_lines`.

L'amorçage écrit en SQL brut (`exec_driver_sql`) pour insérer 20 000 lignes d'un
seul appel : il contourne donc TOUS les défauts portés par l'ORM. Un champ
NOT NULL oublié dans la liste de colonnes fait échouer le démarrage complet de
l'application (init_db est appelé dans le lifespan) — d'où ce test.
"""

import asyncio
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from db.database import Base, _backfill_sale_order_lines
from db.models import SaleOrderLineModel, SaleOrderModel


def _order(order_id, name, lines, *, currency="XOF", amount=0.0):
    return SaleOrderModel(
        order_id=order_id, odoo_id=None, client_id="1", client_name="CIE", name=name,
        amount=amount, currency=currency, date_order=datetime(2026, 5, 22),
        state="sale", salesperson_name="Assamoi", order_lines=lines,
    )


async def _run():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all([
            _order("so_1", "FP/2026/0001", [
                {"product": "Switch Catalyst 9200L", "product_code": "C9200L-48P",
                 "product_category": "Réseau", "qty": 2, "unit_price": 100.0, "subtotal": 200.0},
                # Quantité, PU et sous-total nuls → titre de section, pas une vraie ligne.
                {"product": "LICENCES:", "qty": 0, "unit_price": 0, "subtotal": 0},
            ]),
            # Commande en devise : taux déduit de amount / Σ lignes = 600.
            _order("so_2", "FP/2026/0002", [
                {"product": "Support 8x5", "qty": 1, "unit_price": 50.0, "subtotal": 50.0},
            ], currency="USD", amount=30000.0),
            # Ignorées : pas de lignes à amorcer.
            _order("so_3", "FP/2026/0003", []),
        ])
        await session.commit()

    async with engine.begin() as conn:
        await conn.run_sync(_backfill_sale_order_lines)
        # Second passage : amorçage unique, la table n'est pas re-remplie.
        await conn.run_sync(_backfill_sale_order_lines)

    async with session_factory() as session:
        rows = (await session.execute(
            select(SaleOrderLineModel).order_by(SaleOrderLineModel.line_id)
        )).scalars().all()

    await engine.dispose()
    return rows


def test_backfill_amorce_les_lignes_avec_tous_les_champs_not_null():
    rows = asyncio.run(_run())

    # 2 lignes pour so_1, 1 pour so_2, aucune pour so_3 — et pas de doublon malgré
    # les deux passages.
    assert [r.line_id for r in rows] == ["so_1#0", "so_1#1", "so_2#0"]

    # Le régresseur : `synced_at` est NOT NULL et son défaut n'existe que dans l'ORM,
    # donc l'INSERT brut doit le fournir — et sous un format que SQLAlchemy relit.
    for row in rows:
        assert isinstance(row.synced_at, datetime), row.line_id

    switch = rows[0]
    assert switch.display_type is None
    assert switch.product_code == "C9200L-48P"
    assert switch.product_category == "Réseau"
    assert switch.order_name == "FP/2026/0001"
    assert switch.client_name == "CIE"
    assert (switch.qty, switch.subtotal_xof, switch.subtotal_src) == (2.0, 200.0, 200.0)
    assert switch.fx_status == "exact"

    assert rows[1].display_type == "line_section"

    # Taux déduit : 30000 / 50 = 600. Les montants source restent intacts pour l'audit.
    devise = rows[2]
    assert devise.fx_status == "derived"
    assert devise.currency_src == "USD"
    assert (devise.subtotal_src, devise.subtotal_xof) == (50.0, 30000.0)
    assert devise.unit_price_xof == 30000.0


def test_backfill_ignore_un_json_illisible():
    """Un blob corrompu ne doit pas faire échouer le démarrage de l'application."""

    async def run():
        engine = create_async_engine(
            "sqlite+aiosqlite://", connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession)
        async with session_factory() as session:
            session.add(_order("so_ko", "FP/2026/0009", []))
            await session.commit()

        async with engine.begin() as conn:
            # `order_lines` est typée JSON : l'ORM refuserait de sérialiser une chaîne
            # non-JSON telle quelle, on corrompt donc le blob en SQL brut.
            await conn.exec_driver_sql(
                "UPDATE sale_orders SET order_lines = '{pas du json'"
            )
            await conn.run_sync(_backfill_sale_order_lines)

        async with session_factory() as session:
            rows = (await session.execute(select(SaleOrderLineModel))).scalars().all()
        await engine.dispose()
        return rows

    assert asyncio.run(run()) == []
