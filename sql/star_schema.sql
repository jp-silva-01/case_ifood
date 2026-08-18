-- Arquivo: star_schema.sql
-- Objetivo: ler a camada data/staging/ (ja saneada pela suite de DQ) e materializa o modelo Star Schema no DuckDB.
-- A ordem de criacao é importamte: fato_pedidos vem antes de fato_itens e fato_pagamentos, que se ancoram nela para
-- herdar a exclusao de cancelados.

-- 1. Dimensões
-- clientes
CREATE OR REPLACE TABLE dim_cliente AS
SELECT 
    customer_id,
    customer_unique_id,
    customer_city AS city,
    customer_state AS state
FROM read_csv_auto('data/staging/olist_customers_dataset.csv');

-- vendedores
CREATE OR REPLACE TABLE dim_vendedor AS
SELECT 
    seller_id,
    seller_city AS city,
    seller_state AS state
FROM read_csv_auto('data/staging/olist_sellers_dataset.csv');

-- produtos
-- Produtos sem categoria recebem 'unknown' como membro default. Como 'unknown' nao e uma
-- categoria de negocio, categoria_informada permite exclui-los de rankings sem depender
-- de comparacao com string literal.
CREATE OR REPLACE TABLE dim_produto AS
SELECT
    p.product_id,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category_name,
    p.product_category_name IS NOT NULL AS categoria_informada,
    p.product_weight_g AS weight_g
FROM read_csv_auto('data/staging/olist_products_dataset.csv') p
LEFT JOIN read_csv_auto('data/staging/product_category_name_translation.csv') t 
    ON p.product_category_name = t.product_category_name;

-- Usamos a função nativa do DuckDB para gerar o calendário (dim_tempo)
CREATE OR REPLACE TABLE dim_tempo AS
SELECT 
    d::DATE AS date_id,
    EXTRACT(YEAR FROM d) AS year,
    EXTRACT(MONTH FROM d) AS month,
    EXTRACT(DAY FROM d) AS day,
    DAYNAME(d) AS day_of_week,
    CASE WHEN EXTRACT(ISODOW FROM d) IN (6, 7) THEN TRUE ELSE FALSE END AS is_weekend
FROM generate_series(DATE '2016-01-01', DATE '2019-12-31', INTERVAL 1 DAY) t(d);
-- Restringimos o calendário a um período de dados fechado do dataset, para que os meses sejam ponderados
-- de forma igual em métricas.

-- 2. Tabela Fato: Pedidos (nivel de cabecalho / entregas e avaliacoes)
-- As avaliacoes sao consolidadas antes do join para garantir 1:1 e evitar o fan-out
-- discutido na ADR 002. Ha 551 pedidos com mais de uma avaliacao e 202 com notas
-- divergentes: prevalece a mais recente, e a linha inteira e selecionada de uma vez para
-- que nota e comentario venham sempre do mesmo registro (ADR 014).
CREATE OR REPLACE TABLE fato_pedidos AS
WITH order_reviews AS (
    SELECT order_id, review_score, review_comment_message
    FROM (
        SELECT
            order_id,
            review_score,
            review_comment_message,
            ROW_NUMBER() OVER (
                PARTITION BY order_id
                ORDER BY review_creation_date DESC, review_id
            ) AS rn
        FROM read_csv_auto('data/staging/olist_order_reviews_dataset.csv')
    )
    WHERE rn = 1
)
SELECT 
    o.order_id,
    o.customer_id,
    o.order_status,
    o.order_purchase_timestamp::DATE AS purchase_date_id,
    o.order_purchase_timestamp::TIMESTAMP AS purchase_timestamp,
    o.order_delivered_customer_date::TIMESTAMP AS delivered_timestamp,
    o.order_estimated_delivery_date::TIMESTAMP AS estimated_delivery_timestamp,
    -- Metricas de prazo derivadas aqui, uma vez, em vez de repetidas em cada consulta.
    -- Pedido sem data de entrega resulta em NULL, que nao satisfaz atrasou = TRUE nem
    -- atrasou = FALSE: sai de toda metrica de prazo por construcao (ADR 014).
    DATE_DIFF('day', o.order_purchase_timestamp, o.order_delivered_customer_date) AS prazo_entrega_dias,
    CASE
        WHEN o.order_delivered_customer_date IS NULL THEN NULL
        WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN TRUE
        ELSE FALSE
    END AS atrasou,
    r.review_score,
    r.review_comment_message
FROM read_csv_auto('data/staging/olist_orders_dataset.csv') o
LEFT JOIN order_reviews r ON o.order_id = r.order_id
WHERE o.order_status != 'canceled'; -- Filtramos cancelados logo na raiz para não sujar a análise.

-- 3. Tabela Fato: Itens (nivel linha de produto / receita e frete)
-- O EXISTS propaga a exclusao de cancelados da fato_pedidos. Sem ele, itens de pedidos
-- cancelados ficariam orfaos e inflariam qualquer consulta feita sobre fato_itens
-- isoladamente, violando a relacao identificante do ERD.
CREATE OR REPLACE TABLE fato_itens AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    i.price,
    i.freight_value,
    -- Sinalizado pela suite de DQ, nao descartado: analises que precisem de robustez a
    -- extremos filtram por aqui e o GMV total permanece integro (ADR 007).
    i.is_price_outlier
FROM read_csv_auto('data/staging/olist_order_items_dataset.csv') i
WHERE EXISTS (SELECT 1 FROM fato_pedidos p WHERE p.order_id = i.order_id);

-- 4. Tabela Fato: Pagamentos
-- Mesma propagacao da exclusao de cancelados.
CREATE OR REPLACE TABLE fato_pagamentos AS
SELECT
    pg.order_id,
    pg.payment_sequential,
    pg.payment_type,
    pg.payment_installments,
    pg.payment_value
FROM read_csv_auto('data/staging/olist_order_payments_dataset.csv') pg
WHERE EXISTS (SELECT 1 FROM fato_pedidos p WHERE p.order_id = pg.order_id);
