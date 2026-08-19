# Relatório de Qualidade de Dados (DQ)

Relatório gerado automaticamente pelo pipeline ETL (`python src/etl/main.py`).

## 1. Verificações Automatizadas — Schema, Regras de Negócio e Integridade

Critério de aprovação: confiabilidade $\ge 95\%$ após a aplicação do soft fail.

| Dataset / Módulo | Total Analisado | Falhas Descartadas (Soft Fail) | Confiabilidade (%) | Resultado | Severidade |
| :--- | ---: | ---: | ---: | :---: | :--- |
| Dim_Clientes (Schema) | 99441 | 0 | 100.00% | **PASS** | EXCELENTE |
| Dim_Vendedores (Schema) | 3095 | 0 | 100.00% | **PASS** | EXCELENTE |
| Dim_Produtos (Schema) | 32951 | 0 | 100.00% | **PASS** | EXCELENTE |
| Fato_Pedidos (Schema e Temporalidade) | 99441 | 0 | 100.00% | **PASS** | EXCELENTE |
| Fato_Itens (Schema) | 112650 | 0 | 100.00% | **PASS** | EXCELENTE |
| Fato_Pagamentos (Schema e Boleto) | 103886 | 0 | 100.00% | **PASS** | EXCELENTE |
| Avaliacoes (Schema e Escala 1-5) | 99224 | 0 | 100.00% | **PASS** | EXCELENTE |
| Ref_Pedidos_Clientes | 99441 | 0 | 100.00% | **PASS** | EXCELENTE |
| Ref_Itens_Pedidos | 112650 | 0 | 100.00% | **PASS** | EXCELENTE |
| Ref_Itens_Produtos | 112650 | 0 | 100.00% | **PASS** | EXCELENTE |
| Ref_Itens_Vendedores | 112650 | 0 | 100.00% | **PASS** | EXCELENTE |
| Ref_Pagamentos_Pedidos | 103886 | 0 | 100.00% | **PASS** | EXCELENTE |
| Ref_Avaliacoes_Pedidos | 99224 | 0 | 100.00% | **PASS** | EXCELENTE |

**Resultado consolidado: 13/13 verificações aprovadas.**

## 2. Anomalias Auditadas sem Descarte

Inconsistências reais do dataset que são resolvidas na modelagem em vez de gerar quarentena. Descartar essas linhas custaria mais do que a própria anomalia, mas elas ficam registradas aqui para não passarem silenciosas.

| Anomalia Detectada | Ocorrências | Tratamento Aplicado |
| :--- | ---: | :--- |
| Itens com preço atípico — IQR 3x sobre ln(price) (assimetria=7.92) | 3 | Sinalizados com is_price_outlier acima de R$ 5,213.50; mantidos na fato_itens para não distorcer o GMV |
| Avaliações duplicadas para o mesmo pedido | 551 | Desempate pela avaliação mais recente na fato_pedidos (ADR-02) |
| Pedidos com notas de avaliação divergentes entre si | 202 | Prevalece a avaliação mais recente; nota e comentário vêm da mesma linha |
| Pedidos com status 'delivered' sem data de entrega | 8 | Mantidos na fato_pedidos; excluídos das métricas de prazo por serem NULL |
| Produtos sem categoria cadastrada | 610 | Normalizados como 'unknown' na dim_produto via COALESCE |

## 3. Política de Resiliência

O pipeline adota **soft fail integral**: erros de integridade nos dados brutos não interrompem a esteira. As anomalias são extraídas e depositadas fisicamente em `data/quarantine/`, com a coluna `quarantine_reason` indicando a regra violada, garantindo que a camada `data/staging/` chegue confiável à modelagem dimensional.
