"""
Módulo de Qualidade de Dados e Validações Estatísticas (Data Quality)

Implementa validação declarativa de schemas e regras de negócio com Pandera:
1. Validação estrutural de tipos, não-nulidade e unicidade de chaves primárias.
2. Checagens de consistência temporal e regras de domínio (ex: parcelamento de boleto).
3. Sinalização de outliers de preço adaptada à distribuição dos dados (ADR 007).
4. Validação de integridade referencial entre entidades relacionais.
5. Política de soft fail com segregação física na Quarentena (ADR 003 e 005).
6. Auditoria de anomalias resolvidas na modelagem, reportadas sem descarte.
"""

import pandas as pd
import pandera as pa
from pandera.typing import Series, DateTime
import logging
import os

logger = logging.getLogger(__name__)

# --- Definição dos Schemas de Validação ---

class CustomerSchema(pa.DataFrameModel):
    """
    Schema para validação da dimensão de Clientes e unicidade de customer_id.
    """
    customer_id: Series[str] = pa.Field(nullable=False)
    customer_zip_code_prefix: Series[int] = pa.Field(nullable=False)
    
    @pa.check("customer_id", name="check_unique_customer")
    def check_unique(cls, customer_id: Series[str]) -> Series[bool]:
        return ~customer_id.duplicated()


class SellerSchema(pa.DataFrameModel):
    """
    Schema para validação da dimensão de Vendedores e unicidade de seller_id.
    """
    seller_id: Series[str] = pa.Field(nullable=False)
    
    @pa.check("seller_id", name="check_unique_seller")
    def check_unique(cls, seller_id: Series[str]) -> Series[bool]:
        return ~seller_id.duplicated()


class ProductSchema(pa.DataFrameModel):
    """
    Schema para validação da dimensão de Produtos e unicidade de product_id.
    """
    product_id: Series[str] = pa.Field(nullable=False)
    
    @pa.check("product_id", name="check_unique_product")
    def check_unique(cls, product_id: Series[str]) -> Series[bool]:
        return ~product_id.duplicated()


class OrderSchema(pa.DataFrameModel):
    """
    Schema para validação da Fato de Pedidos.
    Garante unicidade de pedido e consistência temporal (entrega posterior à compra).
    """
    order_id: Series[str] = pa.Field(nullable=False)  
    customer_id: Series[str] = pa.Field(nullable=False)
    order_status: Series[str]
    order_purchase_timestamp: Series[DateTime] = pa.Field(nullable=False)
    order_delivered_customer_date: Series[DateTime] = pa.Field(nullable=True)
    
    @pa.check("order_id", name="regra_2_duplicatas")
    def check_unique(cls, order_id: Series[str]) -> Series[bool]:
        return ~order_id.duplicated()

    @pa.dataframe_check(name="regra_5_inconsistencia_temporal")
    def check_temporal_logic(cls, df: pd.DataFrame) -> pd.Series:
        # Entrega ao cliente não pode ser cronologicamente anterior à compra
        mask = df["order_delivered_customer_date"].notnull()
        return df.loc[mask, "order_delivered_customer_date"] >= df.loc[mask, "order_purchase_timestamp"]


class OrderItemSchema(pa.DataFrameModel):
    """
    Schema para validação estrutural da Fato de Itens de Pedido.

    Outlier de preço é tratado por flag_price_outliers(), que sinaliza em vez de descartar.
    """
    order_id: Series[str] = pa.Field(nullable=False)
    product_id: Series[str] = pa.Field(nullable=False)
    price: Series[float] = pa.Field(ge=0.0)
    freight_value: Series[float] = pa.Field(ge=0.0)


def flag_price_outliers(df: pd.DataFrame, price_col: str = "price") -> tuple[pd.DataFrame, dict]:
    """
    Sinaliza itens com preço anômalo sem removê-los da base.

    Preço alto é fato comercial, não defeito de dado: a regra marca `is_price_outlier` e
    deixa a decisão de excluir para a análise que precise de robustez a extremos.

    O fence é aplicado sobre ln(price) quando a distribuição é assimétrica, porque preço de
    varejo é aproximadamente log-normal e o corte em escala linear cairia dentro da faixa
    comercial legítima. O chaveamento usa assimetria em vez de teste de normalidade: com
    dezenas de milhares de linhas, o teste rejeita normalidade em qualquer cenário.

    Racional completo na ADR 007. Retorna o DataFrame com a coluna e um dicionário de métricas.
    """
    import numpy as np

    serie = df[price_col]
    resultado = df.copy()

    if len(serie.dropna()) < 8:
        resultado["is_price_outlier"] = False
        return resultado, {"metodo": "amostra insuficiente", "limite": None, "sinalizados": 0}

    assimetria = float(serie.skew())
    positivos = serie[serie > 0]

    if abs(assimetria) > 1.0 and len(positivos) >= 8:
        base = np.log(positivos)
        metodo = f"IQR 3x sobre ln({price_col}) (assimetria={assimetria:.2f})"
        q1, q3 = base.quantile(0.25), base.quantile(0.75)
        limite = float(np.exp(q3 + 3 * (q3 - q1)))
    else:
        metodo = f"Z-Score 3 desvios (assimetria={assimetria:.2f})"
        limite = float(serie.mean() + 3 * serie.std())

    resultado["is_price_outlier"] = serie > limite
    sinalizados = int(resultado["is_price_outlier"].sum())

    logger.info(
        f"[Outliers de preço] {metodo}. Limite superior R$ {limite:,.2f}. "
        f"{sinalizados} item(ns) sinalizado(s) -- mantidos na base."
    )

    return resultado, {"metodo": metodo, "limite": limite, "sinalizados": sinalizados}


class PaymentSchema(pa.DataFrameModel):
    """
    Schema para validação da Fato de Pagamentos.
    Garante integridade de valores e regra de negócio para boletos (parcela única).
    """
    order_id: Series[str] = pa.Field(nullable=False)
    payment_type: Series[str] = pa.Field(nullable=False)
    payment_installments: Series[int] = pa.Field(ge=0)
    payment_value: Series[float] = pa.Field(ge=0.0)

    @pa.dataframe_check(name="regra_boleto_parcela_unica")
    def check_boleto_installments(cls, df: pd.DataFrame) -> pd.Series:
        # Pagamentos via boleto bancário devem obrigatoriamente possuir parcela = 1
        is_boleto = df["payment_type"] == "boleto"
        is_valid_installment = df["payment_installments"] == 1
        # É válido se não for boleto OU (for boleto e parcela==1)
        return ~is_boleto | (is_boleto & is_valid_installment)


class ReviewSchema(pa.DataFrameModel):
    """
    Schema para validação estrutural das avaliações de clientes.

    A duplicidade de order_id não é tratada aqui: ela é reportada por audit_soft_anomalies()
    e resolvida no star_schema.sql, que mantém a avaliação mais recente.
    """
    review_id: Series[str] = pa.Field(nullable=False)
    order_id: Series[str] = pa.Field(nullable=False)
    review_score: Series[int] = pa.Field(ge=1, le=5)


# --- Motor de Validação e Política de Soft Fail ---

def validate_dataframe(schema: pa.DataFrameModel, df: pd.DataFrame, df_name: str, file_name: str, quarantine_dir: str) -> tuple:
    """
    Executa validação lazy do Pandera e segrega anomalias em quarentena física.
    
    Retorna o DataFrame saneado, o índice de confiabilidade (%) e as contagens amostrais.
    """
    total_rows = len(df)
    clean_df = df.copy()
    failed_rows = 0
    
    try:
        schema.validate(df, lazy=True)
        logger.info(f"[{df_name}] Validação 100% íntegra.")
    except pa.errors.SchemaErrors as err:
        failure_cases = err.failure_cases.dropna(subset=['index'])
        
        # Consolida múltiplos motivos de violação por índice de linha
        reasons = failure_cases.groupby('index').apply(
            lambda x: " | ".join(f"Violou a regra '{check}'" for check in x['check'].unique())
        ).to_dict()
        
        bad_indices = list(reasons.keys())
        failed_rows = len(bad_indices)
        
        # Isola registros anômalos com rastreabilidade da causa raiz
        bad_df = df.loc[bad_indices].copy()
        bad_df['quarantine_reason'] = bad_df.index.map(reasons)
        
        bad_df.to_csv(os.path.join(quarantine_dir, f"quarantine_schema_{file_name}"), index=False)
        clean_df = df.drop(index=bad_indices)
        
    reliability = 100.0 * (1 - (failed_rows / total_rows)) if total_rows > 0 else 100.0
    return clean_df, reliability, failed_rows, total_rows


def validate_referential_integrity(df_child: pd.DataFrame, child_col: str, df_parent: pd.DataFrame, parent_col: str, rel_name: str, quarantine_dir: str) -> tuple:
    """
    Valida integridade referencial entre entidades pai e filha, isolando registros órfãos.
    """
    total_rows = len(df_child)
    missing_mask = ~df_child[child_col].isin(df_parent[parent_col])
    bad_indices = df_child[missing_mask].index
    failed_rows = len(bad_indices)
    
    if len(bad_indices) > 0:
        logger.warning(f"[Integridade: {rel_name}] Soft Fail: Removendo {failed_rows} registros órfãos.")
        bad_df = df_child.loc[bad_indices].copy()
        bad_df['quarantine_reason'] = f"Órfão: Chave '{child_col}' não existe na tabela pai '{rel_name}'"
        bad_df.to_csv(os.path.join(quarantine_dir, f"quarantine_ref_{rel_name}.csv"), index=False)
        
        df_child = df_child.drop(index=bad_indices)
        
    reliability = 100.0 * (1 - (failed_rows / total_rows)) if total_rows > 0 else 100.0
    return df_child, reliability, failed_rows, total_rows


def audit_soft_anomalies(df_orders: pd.DataFrame, df_products: pd.DataFrame, df_reviews: pd.DataFrame) -> list[dict]:
    """
    Audita inconsistências que são resolvidas na modelagem, sem descartar registros.

    Diferente das regras de schema, nada é removido: descartar custaria mais do que a
    anomalia. Um pedido entregue sem data de entrega ainda é receita válida, e a duplicidade
    de avaliação já é desempatada no star_schema.sql. O propósito é que estes números
    apareçam no relatório em vez de passarem silenciosos.
    """
    dup_reviews = int(df_reviews["order_id"].duplicated().sum())
    conflicting = df_reviews.groupby("order_id")["review_score"].agg(["min", "max"])
    conflicting_scores = int((conflicting["min"] != conflicting["max"]).sum())

    delivered_no_date = int(
        (
            (df_orders["order_status"] == "delivered")
            & (df_orders["order_delivered_customer_date"].isnull())
        ).sum()
    )
    products_no_category = int(df_products["product_category_name"].isnull().sum())

    return [
        {
            "regra": "Avaliações duplicadas para o mesmo pedido",
            "ocorrencias": dup_reviews,
            "tratamento": "Desempate pela avaliação mais recente na fato_pedidos (ADR 014)",
        },
        {
            "regra": "Pedidos com notas de avaliação divergentes entre si",
            "ocorrencias": conflicting_scores,
            "tratamento": "Prevalece a avaliação mais recente; nota e comentário vêm da mesma linha",
        },
        {
            "regra": "Pedidos com status 'delivered' sem data de entrega",
            "ocorrencias": delivered_no_date,
            "tratamento": "Mantidos na fato_pedidos; excluídos das métricas de prazo por serem NULL",
        },
        {
            "regra": "Produtos sem categoria cadastrada",
            "ocorrencias": products_no_category,
            "tratamento": "Normalizados como 'unknown' na dim_produto via COALESCE",
        },
    ]


def generate_dq_report(metrics: dict, audits: list[dict] | None = None, output_path: str = "data_quality_report.md") -> None:
    """
    Gera o relatório executivo em Markdown com status pass/fail e índices de confiabilidade.
    """
    logger.info("Emitindo Data Quality Report (Markdown) com índices de confiabilidade...")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# Relatório de Qualidade de Dados (DQ)\n\n")
        f.write("Relatório gerado automaticamente pelo pipeline ETL (`python src/etl/main.py`).\n\n")
        f.write("## 1. Verificações Automatizadas — Schema, Regras de Negócio e Integridade\n\n")
        f.write("Critério de aprovação: confiabilidade $\\ge 95\\%$ após a aplicação do soft fail.\n\n")
        f.write("| Dataset / Módulo | Total Analisado | Falhas Descartadas (Soft Fail) | Confiabilidade (%) | Resultado | Severidade |\n")
        f.write("| :--- | ---: | ---: | ---: | :---: | :--- |\n")

        for name, data in metrics.items():
            conf = data['reliability']
            status = "PASS" if conf >= 95.0 else "FAIL"
            badge = "EXCELENTE" if conf >= 99.0 else ("ACEITÁVEL" if conf >= 95.0 else "CRÍTICO")
            f.write(f"| {name} | {data['total']} | {data['failed']} | {conf:.2f}% | **{status}** | {badge} |\n")

        total_checks = len(metrics)
        passed = sum(1 for d in metrics.values() if d['reliability'] >= 95.0)
        f.write(f"\n**Resultado consolidado: {passed}/{total_checks} verificações aprovadas.**\n")

        if audits:
            f.write("\n## 2. Anomalias Auditadas sem Descarte\n\n")
            f.write("Inconsistências reais do dataset que são resolvidas na modelagem em vez de gerar ")
            f.write("quarentena. Descartar essas linhas custaria mais do que a própria anomalia, ")
            f.write("mas elas ficam registradas aqui para não passarem silenciosas.\n\n")
            f.write("| Anomalia Detectada | Ocorrências | Tratamento Aplicado |\n")
            f.write("| :--- | ---: | :--- |\n")
            for a in audits:
                f.write(f"| {a['regra']} | {a['ocorrencias']} | {a['tratamento']} |\n")

        f.write("\n## 3. Política de Resiliência\n\n")
        f.write("O pipeline adota **soft fail integral**: erros de integridade nos dados brutos não ")
        f.write("interrompem a esteira. As anomalias são extraídas e depositadas fisicamente em ")
        f.write("`data/quarantine/`, com a coluna `quarantine_reason` indicando a regra violada, ")
        f.write("garantindo que a camada `data/staging/` chegue confiável à modelagem dimensional.\n")

# --- Orquestrador do Pipeline de QA ---

def run_dq_pipeline(raw_dir: str = "data/raw", staging_dir: str = "data/staging", quarantine_dir: str = "data/quarantine") -> bool:
    """
    Orquestra as validações, remove dado sujo e promove o dado limpo para a camada 'staging'.
    Retorna SEMPRE True, confiando no Soft Fail e nos índices de representatividade.
    """
    logger.info("Acionando suíte de testes...")
    if not os.path.exists(staging_dir):
        os.makedirs(staging_dir)
    if not os.path.exists(quarantine_dir):
        os.makedirs(quarantine_dir)
        
    metrics = {}
    
    try:
        # Carga dos datasets brutos
        df_orders = pd.read_csv(os.path.join(raw_dir, "olist_orders_dataset.csv"), parse_dates=["order_purchase_timestamp", "order_delivered_customer_date"])
        df_items = pd.read_csv(os.path.join(raw_dir, "olist_order_items_dataset.csv"))
        df_products = pd.read_csv(os.path.join(raw_dir, "olist_products_dataset.csv"))
        df_customers = pd.read_csv(os.path.join(raw_dir, "olist_customers_dataset.csv"))
        df_sellers = pd.read_csv(os.path.join(raw_dir, "olist_sellers_dataset.csv"))
        df_payments = pd.read_csv(os.path.join(raw_dir, "olist_order_payments_dataset.csv"))
        df_reviews = pd.read_csv(os.path.join(raw_dir, "olist_order_reviews_dataset.csv"))

        # 1. Validação de Schemas e Regras de Domínio
        df_customers_clean, rel, fail, tot = validate_dataframe(CustomerSchema, df_customers, "Dim_Clientes", "customers.csv", quarantine_dir)
        metrics["Dim_Clientes (Schema)"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        df_sellers_clean, rel, fail, tot = validate_dataframe(SellerSchema, df_sellers, "Dim_Vendedores", "sellers.csv", quarantine_dir)
        metrics["Dim_Vendedores (Schema)"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        df_products_clean, rel, fail, tot = validate_dataframe(ProductSchema, df_products, "Dim_Produtos", "products.csv", quarantine_dir)
        metrics["Dim_Produtos (Schema)"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        df_orders_clean, rel, fail, tot = validate_dataframe(OrderSchema, df_orders, "Fato_Pedidos", "orders.csv", quarantine_dir)
        metrics["Fato_Pedidos (Schema e Temporalidade)"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        df_items_clean, rel, fail, tot = validate_dataframe(OrderItemSchema, df_items, "Fato_Itens", "items.csv", quarantine_dir)
        metrics["Fato_Itens (Schema)"] = {'total': tot, 'failed': fail, 'reliability': rel}

        # Sinalizacao, nao descarte (ADR 007).
        df_items_clean, outlier_stats = flag_price_outliers(df_items_clean)

        df_payments_clean, rel, fail, tot = validate_dataframe(PaymentSchema, df_payments, "Fato_Pagamentos", "payments.csv", quarantine_dir)
        metrics["Fato_Pagamentos (Schema e Boleto)"] = {'total': tot, 'failed': fail, 'reliability': rel}

        df_reviews_clean, rel, fail, tot = validate_dataframe(ReviewSchema, df_reviews, "Avaliacoes", "reviews.csv", quarantine_dir)
        metrics["Avaliacoes (Schema e Escala 1-5)"] = {'total': tot, 'failed': fail, 'reliability': rel}

        # 2. Validação de Integridade Referencial (Chaves Estrangeiras)
        df_orders_clean, rel, fail, tot = validate_referential_integrity(df_orders_clean, 'customer_id', df_customers_clean, 'customer_id', 'orders_to_customers', quarantine_dir)
        metrics["Ref_Pedidos_Clientes"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        # Items -> Orders
        df_items_clean, rel, fail, tot = validate_referential_integrity(df_items_clean, 'order_id', df_orders_clean, 'order_id', 'items_to_orders', quarantine_dir)
        metrics["Ref_Itens_Pedidos"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        # Items -> Products
        df_items_clean, rel, fail, tot = validate_referential_integrity(df_items_clean, 'product_id', df_products_clean, 'product_id', 'items_to_products', quarantine_dir)
        metrics["Ref_Itens_Produtos"] = {'total': tot, 'failed': fail, 'reliability': rel}
        
        # Items -> Sellers
        df_items_clean, rel, fail, tot = validate_referential_integrity(df_items_clean, 'seller_id', df_sellers_clean, 'seller_id', 'items_to_sellers', quarantine_dir)
        metrics["Ref_Itens_Vendedores"] = {'total': tot, 'failed': fail, 'reliability': rel}

        # Payments -> Orders
        df_payments_clean, rel, fail, tot = validate_referential_integrity(df_payments_clean, 'order_id', df_orders_clean, 'order_id', 'payments_to_orders', quarantine_dir)
        metrics["Ref_Pagamentos_Pedidos"] = {'total': tot, 'failed': fail, 'reliability': rel}

        # Reviews -> Orders (avaliações órfãs seriam perdidas silenciosamente no LEFT JOIN do SQL)
        df_reviews_clean, rel, fail, tot = validate_referential_integrity(df_reviews_clean, 'order_id', df_orders_clean, 'order_id', 'reviews_to_orders', quarantine_dir)
        metrics["Ref_Avaliacoes_Pedidos"] = {'total': tot, 'failed': fail, 'reliability': rel}

        # 3. Auditoria de anomalias resolvidas na modelagem (sem descarte)
        audits = audit_soft_anomalies(df_orders_clean, df_products_clean, df_reviews_clean)
        audits.insert(0, {
            "regra": f"Itens com preço atípico — {outlier_stats['metodo']}",
            "ocorrencias": outlier_stats['sinalizados'],
            "tratamento": (
                f"Sinalizados com is_price_outlier acima de R$ {outlier_stats['limite']:,.2f}; "
                "mantidos na fato_itens para não distorcer o GMV"
            ),
        })
        for a in audits:
            logger.info(f"[Auditoria] {a['regra']}: {a['ocorrencias']} ocorrência(s).")

        # 4. Persistência dos dados purificados em Staging
        logger.info("Movendo dados purificados para a camada analítica (Staging)...")
        df_orders_clean.to_csv(os.path.join(staging_dir, "olist_orders_dataset.csv"), index=False)
        df_items_clean.to_csv(os.path.join(staging_dir, "olist_order_items_dataset.csv"), index=False)
        df_products_clean.to_csv(os.path.join(staging_dir, "olist_products_dataset.csv"), index=False)
        df_customers_clean.to_csv(os.path.join(staging_dir, "olist_customers_dataset.csv"), index=False)
        df_sellers_clean.to_csv(os.path.join(staging_dir, "olist_sellers_dataset.csv"), index=False)
        df_payments_clean.to_csv(os.path.join(staging_dir, "olist_order_payments_dataset.csv"), index=False)
        df_reviews_clean.to_csv(os.path.join(staging_dir, "olist_order_reviews_dataset.csv"), index=False)

        # A tabela de tradução de categorias é um de-para estático, sem regra de negócio a validar.
        translation = "product_category_name_translation.csv"
        src = os.path.join(raw_dir, translation)
        if os.path.exists(src):
            with open(src, 'rb') as f_in, open(os.path.join(staging_dir, translation), 'wb') as f_out:
                f_out.write(f_in.read())

    except FileNotFoundError as e:
        logger.error(f"Erro ao carregar dados: {e}")
        return False

    generate_dq_report(metrics, audits=audits)
    return True
