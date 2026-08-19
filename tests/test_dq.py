"""
Testes unitários da suíte de Data Quality.

Cobrem as duas decisões que a suíte toma sobre o dado: segregar o que viola a chave
primária e sinalizar, sem remover, o preço atípico. Operam sobre DataFrames construídos
no próprio teste, sem depender do dataset da Olist nem do banco materializado.
"""

import numpy as np
import pandas as pd
import pytest

from src.dq.validators import CustomerSchema, flag_price_outliers, validate_dataframe


# --- Validação de schema e regras de domínio ---

def test_chave_duplicada_vai_para_quarentena(tmp_path):
    """customer_id repetido deve ser segregado, preservando a primeira ocorrência."""
    df = pd.DataFrame({
        "customer_id": ["a", "b", "b", "c"],
        "customer_zip_code_prefix": [1000, 2000, 2000, 3000],
    })

    limpo, confiabilidade, falhas, total = validate_dataframe(
        CustomerSchema, df, "Dim_Clientes", "customers.csv", str(tmp_path)
    )

    assert total == 4
    assert falhas == 1
    assert len(limpo) == 3
    assert limpo["customer_id"].is_unique
    assert confiabilidade == pytest.approx(75.0)
    assert (tmp_path / "quarantine_schema_customers.csv").exists()


# --- Sinalização de outlier de preço (ADR-04) ---

def test_outlier_de_preco_e_sinalizado_sem_ser_removido():
    """
    Trava as duas propriedades da regra: nenhuma linha desaparece e o extremo é marcado.
    """
    rng = np.random.default_rng(42)
    precos = list(np.exp(rng.normal(4.0, 0.6, 500)))  # log-normal, como preço de varejo
    precos.append(500_000.0)                          # erro de lançamento evidente
    df = pd.DataFrame({"price": precos})

    resultado, stats = flag_price_outliers(df)

    assert len(resultado) == len(df), "a sinalização não pode descartar linhas"
    assert resultado["is_price_outlier"].sum() >= 1
    assert bool(resultado["is_price_outlier"].iloc[-1]), "o valor absurdo deve ser sinalizado"
    assert stats["limite"] > 0

