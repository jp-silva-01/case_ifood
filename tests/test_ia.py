"""
Suíte de Testes Automatizados do Módulo de IA (NLP & Data Warehouse)

Valida os componentes estruturais do pipeline de Inteligência Artificial:
1. Validação estrita de tipagem e contratos Pydantic (Structured Output).
2. Persistência relacional das predições na tabela 'fato_reviews_classificados' do DuckDB.
"""

import os
import duckdb
import pytest
from src.ia.classify_reviews import (
    ReviewClassification,
    persist_classifications_to_duckdb,
    CategoryDefinition,
    TaxonomyDiscoveryOutput
)


@pytest.fixture
def test_db_path(tmp_path):
    """
    Cria um banco DuckDB isolado em diretório temporário para os testes de integração.
    """
    db_file = str(tmp_path / "test_olist.duckdb")
    conn = duckdb.connect(db_file)
    
    # Cria estrutura mínima da fato_pedidos para simulação
    conn.execute("""
        CREATE TABLE fato_pedidos (
            order_id VARCHAR PRIMARY KEY,
            review_score INT,
            review_comment_message VARCHAR
        );
        INSERT INTO fato_pedidos VALUES
            ('order_1', 1, 'Produto nao foi entregue e atrasou muito'),
            ('order_2', 1, 'Veio faltando um item do pacote'),
            ('order_3', 2, 'Produto falsificado de péssima qualidade');
    """)
    conn.close()
    return db_file


def test_persist_classifications_in_duckdb(test_db_path):
    """
    Testa a persistência transacional das classificações de reviews na tabela fato_reviews_classificados.
    Valida integridade colunar, contagem de registros e tipos mapeados.
    """
    mock_classifications = [
        ReviewClassification(
            order_id="order_1",
            categoria_primaria="atraso_entrega",
            motivo_especifico="Produto atrasado",
            severidade="alta",
            reclamou_prazo=True,
            reclamou_produto=False,
            reclamou_atendimento=False
        ),
        ReviewClassification(
            order_id="order_2",
            categoria_primaria="item_incompleto",
            motivo_especifico="Veio faltando item",
            severidade="media",
            reclamou_prazo=False,
            reclamou_produto=True,
            reclamou_atendimento=False
        ),
        ReviewClassification(
            order_id="order_3",
            categoria_primaria="qualidade_produto",
            motivo_especifico="Produto falsificado",
            severidade="alta",
            reclamou_prazo=False,
            reclamou_produto=True,
            reclamou_atendimento=False
        )
    ]
    
    # Executa a persistência no banco temporário
    persist_classifications_to_duckdb(mock_classifications, db_path=test_db_path)
    
    conn = duckdb.connect(test_db_path)
    count = conn.execute("SELECT COUNT(*) FROM fato_reviews_classificados").fetchone()[0]
    df = conn.execute("SELECT * FROM fato_reviews_classificados ORDER BY order_id").df()
    conn.close()
    
    assert count == 3
    assert df.loc[0, 'categoria_primaria'] == 'atraso_entrega'
    assert df.loc[1, 'motivo_especifico'] == 'Veio faltando item'
    assert df.loc[2, 'severidade'] == 'alta'


def test_pydantic_schema_validation():
    """
    Valida a conformidade dos modelos Pydantic com os contratos de Structured Output.
    Garante que tipagem e campos aninhados atendem aos requisitos da API.
    """
    cat = CategoryDefinition(
        category_id="atraso_logistico",
        display_name="Atraso Logístico",
        description="Atrasos na entrega",
        keywords=["atraso", "demora"]
    )
    tax = TaxonomyDiscoveryOutput(
        categories=[cat],
        summary="Atrasos frequentes"
    )
    assert tax.categories[0].category_id == "atraso_logistico"
    assert len(tax.categories[0].keywords) == 2
