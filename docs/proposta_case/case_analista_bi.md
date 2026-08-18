
# Analytics Engineer
### Case Técnico • 3 dias

> **Transformar dados brutos de e-commerce em recomendação acionável para o CEO — combinando engenharia de dados, IA aplicada e pensamento estratégico.**

---

### 📦 O Desafio

Você é a pessoa Analista de BI recém-chegada. O CEO pediu:

> *"Quais são as alavancas mais efetivas para aumentar a receita nos próximos 6 meses?"*

Sua missão é responder essa pergunta usando o dataset abaixo.

#### 📦 Brazilian E-Commerce Public Dataset by Olist
- **Link:** [kaggle.com/datasets/olistbr/brazilian-ecommerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
- **Detalhes:** 9 tabelas relacionais • ~100k pedidos (2016–2018) • clientes, vendedores, produtos, pedidos, pagamentos, avaliações, geolocalização, itens, tradução de categorias

---

### 🧩 As 6 Etapas

#### 1. Modelagem de Dados
- Baixar CSVs, criar modelo relacional (estrela/snowflake), documentar ERD com justificativas de granularidade, chaves e normalização.
- `SQL` `Modelagem`

#### 2. Qualidade de Dados
- Suíte de validação: nulos, duplicatas, outliers, integridade referencial, inconsistências temporais.
- Data quality report com $\ge 5$ verificações automatizadas.
- `Python` `DQ`

#### 3. Pipeline ETL/ELT
- Pipeline reprodutível: ingerir CSVs $\rightarrow$ limpar $\rightarrow$ transformar.
- Com teste automatizado. Qualquer pessoa deve conseguir rodar do zero.
- `Python` `SQL`

#### 4. Análise Exploratória
- Responder 5 perguntas de negócio:
  1. Sazonalidade
  2. Categorias rentáveis
  3. Impacto de delivery em recompra
  4. CLV por região
  5. Concentração de vendedores
- Visualizações comentadas.
- `Python` `SQL`

#### 5. Automação com IA
- LLM para: resumo executivo automático, classificação de reviews, ou agente Q&A sobre os dados.
- Código versionado, reprodutível. Justificar a abordagem escolhida.
- `IA/LLM` `Python`

#### 6. Recomendação ao CEO
- One-pager executivo (máx 1 pág): 3 alavancas de receita com impacto estimado ($/\%), racional analítico, plano de ação 6 meses, riscos e trade-offs.
- Acionável em 3 min de leitura.
- `Business` `Comunicação`

---

### 📦 Formato de Entrega

Um único repositório Git contendo:

| Artefato | Formato | O que esperamos |
| :--- | :--- | :--- |
| **README.md** | Markdown | Visão geral, instruções para rodar, ERD, decisões de design |
| **Pipeline ETL** | Python + SQL | Código limpo, type hints, docstrings, testes, reprodutível |
| **Data Quality Report** | Notebook / Script | Checagens automatizadas com output claro (pass/fail) |
| **Análise Exploratória** | Jupyter Notebook | Visualizações comentadas, queries SQL, conclusões parciais |
| **Automação com IA** | Script Python | Versionado, requirements.txt, instruções de uso |
| **One-pager Executivo** | PDF ou Markdown | Máximo 1 página. Recomendação, dados que a sustentam, plano de ação |

---

### 🏆 Critérios de Avaliação

| Dimensão | Peso | O que avalia |
| :--- | :---: | :--- |
| **Modelagem de Dados** | **20%** | Escolha de esquema, granularidade, justificativas, ERD documentado |
| **Qualidade & Engenharia** | **20%** | Pipeline reprodutível, testes, tratamento de bordas, código limpo |
| **Profundidade Analítica** | **20%** | Perguntas respondidas com rigor, estatística, visualizações efetivas |
| **IA Aplicada** | **15%** | Uso pragmático de LLM, integração com pipeline de dados, justificativa |
| **Business Acumen** | **15%** | Recomendação acionável, clareza, priorização, trade-offs |
| **Documentação** | **10%** | README, comentários, decisões explicadas, reprodutibilidade |

---

> 💡 **O que valorizamos:** pragmatismo (simples e completo > complexo e inacabado), decisões documentadas, código que roda sem ajuda, e IA resolvendo problema real — não demo de chatbot.

---

*Case para processo seletivo de Analista de BI • 2026*  
*Dúvidas? Entre em contato com a pessoa recrutadora.*
