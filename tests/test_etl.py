"""
Testes do pipeline ETL e da modelagem dimensional.

Validam o Data Warehouse materializado em DuckDB: existência do arquivo, presença das
4 dimensões e 3 fatos do Star Schema, não-nulidade das chaves de granularidade, o grão
de um pedido por linha e a integridade referencial entre as fatos.
"""

import os
import duckdb
import pytest

DB_PATH = 'data/processed/olist.duckdb'


def test_database_exists():
    """
    Valida se o arquivo do banco colunar DuckDB foi gerado fisicamente no disco.
    """
    assert os.path.exists(DB_PATH), "Banco analítico não foi encontrado em data/processed/olist.duckdb."


def test_tables_exist():
    """
    Valida a presença de todas as entidades do modelo dimensional Star Schema.
    Garante que o DDL/DML em sql/star_schema.sql foi executado.
    """
    conn = duckdb.connect(DB_PATH)
    tables = conn.execute("SHOW TABLES").df()['name'].tolist()
    
    expected_tables = [
        'dim_cliente',
        'dim_produto',
        'dim_tempo',
        'dim_vendedor',
        'fato_itens',
        'fato_pagamentos',
        'fato_pedidos'
    ]
    
    for table in expected_tables:
        assert table in tables, f"Tabela {table} ausente no Star Schema."
        
    conn.close()


def test_primary_keys_not_null():
    """
    Valida a integridade referencial básica e não-nulidade das chaves de granularidade das Fatos.
    """
    conn = duckdb.connect(DB_PATH)
    
    null_pedidos = conn.execute("SELECT COUNT(*) FROM fato_pedidos WHERE order_id IS NULL").fetchone()[0]
    assert null_pedidos == 0, "fato_pedidos possui order_id nulo"
    
    null_itens = conn.execute("SELECT COUNT(*) FROM fato_itens WHERE order_item_id IS NULL").fetchone()[0]
    assert null_itens == 0, "fato_itens possui order_item_id nulo"

    conn.close()


def test_grao_da_fato_pedidos():
    """
    Garante o grão declarado na ADR 002: 1 linha = 1 pedido.

    É a propriedade que a deduplicação de avaliações pode quebrar -- os pedidos com mais de
    uma avaliação multiplicariam linhas aqui se o desempate falhar.
    """
    conn = duckdb.connect(DB_PATH)
    total, distintos = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT order_id) FROM fato_pedidos"
    ).fetchone()
    conn.close()

    assert total == distintos, (
        f"fato_pedidos tem {total} linhas para {distintos} pedidos distintos -- "
        "o grão de cabeçalho foi violado (provável fan-out de avaliações)."
    )


def test_integridade_referencial_das_fatos():
    """
    Garante que as três fatos descrevem o mesmo universo de pedidos.

    Sem a propagação da exclusão de cancelados, itens e pagamentos órfãos entrariam em
    qualquer consulta feita diretamente sobre fato_itens.
    """
    conn = duckdb.connect(DB_PATH)

    itens_orfaos = conn.execute("""
        SELECT COUNT(*) FROM fato_itens i
        LEFT JOIN fato_pedidos p USING (order_id)
        WHERE p.order_id IS NULL
    """).fetchone()[0]

    pagamentos_orfaos = conn.execute("""
        SELECT COUNT(*) FROM fato_pagamentos pg
        LEFT JOIN fato_pedidos p USING (order_id)
        WHERE p.order_id IS NULL
    """).fetchone()[0]

    conn.close()

    assert itens_orfaos == 0, f"{itens_orfaos} itens sem pedido correspondente em fato_pedidos."
    assert pagamentos_orfaos == 0, f"{pagamentos_orfaos} pagamentos sem pedido correspondente."
