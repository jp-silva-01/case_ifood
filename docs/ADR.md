# Registro de Decisões de Arquitetura (ADR)

Este documento registra as decisões de arquitetura e modelagem tomadas na construção da solução. Cada entrada segue o formato padrão de ADR — contexto, decisão, alternativas consideradas e consequência e traz o trade-off.

---

## Índice

| ADR | Decisão | Status |
| :---: | :--- | :---: |
| [01](#adr-01-modelagem-dimensional-star-schema) | Modelagem Dimensional (Star Schema) | Aceito |
| [02](#adr-02-fatos-múltiplas-grão-e-propagação-de-filtros) | Fatos múltiplas, grão e propagação de filtros | Aceito |
| [03](#adr-03-qualidade-de-dados-pandera--soft-fail) | Qualidade de dados: Pandera + soft-fail | Aceito |
| [04](#adr-04-detecção-de-outlier-de-preço-em-escala-logarítmica) | Detecção de outlier de preço em escala logarítmica | Aceito |
| [05](#adr-05-engine-local-duckdb--sql-ingestão-com-fallback) | Engine local: DuckDB + SQL, ingestão com fallback | Aceito |
| [06](#adr-06-escopo-e-desenho-do-módulo-de-ia) | Escopo e desenho do módulo de IA | Aceito |

---

## ADR-01: Modelagem Dimensional (Star Schema)

**Status:** Aceito

**Contexto.** A base da Olist tem 9 tabelas relacionais em formato transacional. O consumo é analítico (BI, notebooks), o que pede um modelo que evite joins excessivos em tempo de consulta.

**Decisão.** Star Schema no DuckDB: dimensões conformadas `dim_cliente`, `dim_vendedor`, `dim_produto`, `dim_tempo`, conectadas às fatos. `dim_tempo` é gerada via `generate_series` (2016–2019) em vez de arquivo estático. `dim_produto` traduz categoria via `COALESCE(tradução, original, 'unknown')`.

**Alternativas consideradas.** Snowflake schema: descartado por adicionar normalização e joins sem ganho analítico neste escopo. Arquivo de calendário estático para `dim_tempo` — descartado em favor da geração nativa, que não exige manutenção.

**Consequência.** Execução colunar com baixa complexidade de consulta. Separação estrita entre métricas aditivas (fatos) e atributos categóricos de filtro (dimensões) simplifica o consumo em notebooks e SQL direto.

---

## ADR-02: Fatos múltiplas, grão e propagação de filtros

**Status:** Aceito

**Contexto.** A proposta inicial previa duas fatos (`fato_pedidos` no grão de cabeçalho, `fato_itens` no grão de item). Três fontes de fan-out tornam isso inviável: pedidos com múltiplos pagamentos (até 29 transações por pedido), pedidos com múltiplas avaliações e pedidos cancelados que não deveriam contar como receita.

**Decisão.** Quatro fatos independentes por grão: `fato_pedidos` (1 pedido), `fato_itens` (1 item), `fato_pagamentos` (1 transação), `fato_reviews_classificados` (1 avaliação classificada pela IA). O filtro `order_status != 'canceled'` é aplicado uma vez em `fato_pedidos` e propagado a `fato_itens`/`fato_pagamentos` via `EXISTS`, garantindo que as três descrevam o mesmo universo de pedidos. A consolidação de avaliações usa `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY review_creation_date DESC, review_id)`, trazendo nota e comentário da mesma linha. `prazo_entrega_dias` e `atrasou` são calculados uma vez no modelo; ausência de data de entrega resulta em `NULL`, que exclui o pedido de métricas de prazo por construção. `dim_produto.categoria_informada` torna explícito o filtro de produtos sem categoria em vez de depender de comparação com a string `'unknown'`.

**Alternativas consideradas.** Fato única com todos os grãos — descartada: multiplicaria linhas e duplicaria `SUM(price)`/`SUM(payment_value)`.
Desempate de avaliações por `MAX(review_score)` + `FIRST(comentário)` — descartado: `FIRST()` sem `ORDER BY` não é determinístico no DuckDB, e `MAX()` enviesa a satisfação para cima, subestimando detratores (a população que alimenta o módulo de IA).

**Consequência.** Sem a propagação do filtro, 542 itens e 664 pagamentos ficariam órfãos (R$ 95 mil de GMV cancelado entrando em qualquer consulta direta sobre `fato_itens`), violando a relação identificante do ERD. Cada análise usa a fato correta por grão: receita e produto em `fato_itens`, parcelamento em `fato_pagamentos`, ciclo de entrega e satisfação em `fato_pedidos`. O trade-off é que qualquer nova fato precisa repetir explicitamente a propagação do filtro — a suíte de testes (`test_integridade_referencial_das_fatos`, `test_grao_da_fato_pedidos`) existe para travar essa regressão.

---

## ADR-03: Qualidade de dados: Pandera + soft-fail

**Status:** Aceito

**Contexto.** O case exige verificação automatizada com relatório claro (pass/fail) e no mínimo 5 checagens. Interromper a esteira a cada violação isolada (um preço negativo, uma chave estrangeira órfã) não é viável para um pipeline de mais de 100 mil transações.

**Decisão.** Schemas Pandera (`DataFrameModel`) tipados para as 7 entidades, cobrindo tipo, nulidade, unicidade de chave, regra temporal (`delivered >= purchase`) e regra de domínio (boleto exige parcela única), somados a checagem de integridade referencial em 6 relacionamentos. Política de soft-fail: linhas violadoras e órfãs são movidas para `data/quarantine/` com a coluna `quarantine_reason`; a esteira nunca é interrompida. `data_quality_report.md` é emitido a cada execução com confiabilidade (%) por verificação.

**Alternativas consideradas.** Hard-fail (abortar no primeiro erro) — descartado: inviabiliza a continuidade analítica em um dataset desse volume e não reflete como uma ingestão real precisa se comportar.

**Consequência.** 13/13 verificações aprovadas com 100% de confiabilidade no dataset atual: a base pública da Olist não viola nenhuma das regras testadas, então `data/quarantine/` fica vazia numa execução normal. O mecanismo de segregação é exercitado em `tests/test_dq.py`, que injeta uma chave duplicada sintética e verifica que o arquivo de quarentena é escrito. O trade-off do soft-fail é exigir vigilância: dado descartado silenciosamente é um risco, por isso o relatório é gerado a cada rodada em vez de sob demanda.

---

## ADR-04: Detecção de outlier de preço em escala logarítmica

**Status:** Aceito

**Contexto.** Preço de e-commerce é assimétrico (assimetria observada de 7,95). Um fence padrão (`Q3 + 3×IQR`) sobre a escala linear resulta em R$ 419,90, esse corte classificaria 4.074 itens (3,6% das linhas, mas 24,9% do GMV — R$ 3,38 milhões) como outlier. A mediana desses itens é R$ 659: catálogo real de móveis, eletrodomésticos e informática, não erro de lançamento.

**Decisão.** O fence é calculado sobre `ln(price)` quando `|assimetria| > 1`, o que move o corte para ~R$ 5.213 e isola 3 itens em 112.650 (0,003% das linhas). O item permanece na base e a coluna `is_price_outlier` sinaliza em vez de remover. A decisão de excluir um item extremo passa a ser da análise que precisa de robustez a extremos, não da ingestão.

**Alternativas consideradas.** Z-score fixo (±3σ) — descartado, distorcido pela assimetria. Teste de normalidade (D'Agostino) para chavear entre métodos — descartado: com n > 100 mil o teste rejeita normalidade em qualquer cenário, tornando o chaveamento decorativo; o critério final usa assimetria (`|skew| > 1`), que mede diretamente o que importa para a escolha do fence.

**Consequência.** O GMV analisável volta a corresponder ao GMV observado: os R$ 3,38 milhões que o corte linear descartaria seguem na base. `tests/test_dq.py` trava as duas propriedades da regra: nenhuma linha desaparece e o extremo real é marcado. O trade-off é que qualquer análise sensível a outliers (ex.: ticket médio) precisa filtrar `is_price_outlier` explicitamente, pois a base não filtra por padrão.

---

## ADR-05: Engine local: DuckDB + SQL, ingestão com fallback

**Status:** Aceito

**Contexto.** Avaliou-se dbt versus uma solução autocontida em Python + SQL para as transformações. Separadamente, a ingestão via API do Kaggle não pode ser uma dependência rígida: falta de credencial (`kaggle.json`) ou instabilidade de rede bloquearia a execução por um avaliador.

**Decisão.** DuckDB executando SQL puro (`sql/star_schema.sql`), orquestrado por `src/etl/main.py`, persistido em `data/processed/olist.duckdb`. A ingestão tenta `kagglehub` primeiro; em caso de falha ou ausência de credencial, chaveia automaticamente para os arquivos já presentes em `data/raw/`.

**Alternativas consideradas.** dbt — descartado: exigiria arquivos de perfil e dependências de ambiente desproporcionais ao escopo do projeto. Dependência obrigatória da API do Kaggle — descartada: bloquearia a reprodução do pipeline por quem avalia sem credencial própria.

**Consequência.** Pipeline completo roda com um único comando (`python src/etl/main.py`), sem serviço externo. O `.duckdb` é versionado no repositório propositalmente: mesmo sem rodar a ingestão, os notebooks abrem e reproduzem as análises.

---

## ADR-06: Escopo e desenho do módulo de IA

**Status:** Aceito

**Contexto.** O módulo de IA precisa resolver um problema real de diagnóstico, não demonstrar uso de LLM. Dois terços dos clientes que dão nota 1 ou 2 receberam o pedido no prazo, nenhuma métrica operacional explica essa insatisfação; só o texto da avaliação explica.

**Decisão.** SDK oficial `google-genai` com *Structured Output* validado por Pydantic, em duas fases: (1) descoberta de taxonomia — o modelo analisa uma amostra e propõe de 4 a 6 categorias mutuamente exclusivas, evitando categorias pré-definidas a priori; (2) classificação em lotes de 50 avaliações contra essa taxonomia, persistida em `fato_reviews_classificados`, dimensão consultável em SQL. O escopo da IA é estritamente NLP tático — extrair `categoria_primaria`, `motivo_especifico`, `severidade` e flags booleanas de texto não estruturado. A formulação das 3 alavancas, o dimensionamento em R$ e a redação do one-pager são 100% analíticos e humanos. Salvaguardas: amostragem `reservoir` com semente fixa (42, reprodutível); lote com falha de API é marcado `categoria_primaria = 'nao_classificado'` e `is_fallback = TRUE`, excluído de qualquer percentual; a tabela é recriada a cada execução com `run_id`, pois a taxonomia é redescoberta a cada rodada.

**Alternativas consideradas.** `litellm` como camada multi-provedor — descartado: dependência extra sem necessidade real neste escopo, com instabilidade de contrato JSON e incompatibilidade com versões recentes do Gemini. Categorias de queixa pré-definidas manualmente — descartadas: introduzem viés de confirmação e tendem a não cobrir o que os clientes de fato escrevem. IA gerando o resumo executivo ou sugerindo as próprias alavancas — descartado: saída não determinística é incompatível com uma decisão executiva, e delegaria à IA justamente o julgamento analítico que o case avalia.

**Consequência.** Um número da taxonomia só chega ao one-pager se nenhum lote tiver caído em fallback. Os notebooks reportam o tamanho da amostra ao lado de cada percentual — a amostra classificada cobre uma fração pequena do universo de detratores com texto, então a distribuição é lida como ordem de grandeza, não como medida exata.

