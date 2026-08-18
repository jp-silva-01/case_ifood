"""
Módulo de Inteligência Artificial e Enriquecimento Semântico (NLP & Data Warehouse)

Implementa pipeline de processamento de linguagem natural em duas fases (ADR 008 e 009):
1. Descoberta não-supervisionada de taxonomia de detração via LLM (Topic Discovery).
2. Classificação semântica em lote com validação estrita de schema (Pydantic / Structured Output).
3. Persistência relacional dos atributos enriquecidos na tabela 'fato_reviews_classificados' do DuckDB.
"""

import os
import sys
import json
import logging
import uuid
from datetime import datetime
from dotenv import load_dotenv
import duckdb
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Configuração de logging estruturado
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# Modelos homologados com fallback automático de versão
DEFAULT_MODELS = [
    os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

# Detração é 1 ou 2 estrelas.
DETRACTOR_SCORE_MAX = 2

# Rótulo reservado a lotes cuja chamada ao modelo falhou. Nunca pertence à taxonomia
# descoberta, o que mantém esses registros filtráveis em SQL.
CATEGORIA_NAO_CLASSIFICADA = "nao_classificado"

# Semente fixa da amostragem para que a execução seja reproduzível.
SAMPLE_SEED = 42

# --- Modelos Pydantic Para Structured Output (Contratos De Dados) ---

class CategoryDefinition(BaseModel):
    """
    Contrato para definição de uma categoria na descoberta de taxonomia.
    """
    category_id: str = Field(description="Identificador snake_case da categoria, ex: atraso_entrega")
    display_name: str = Field(description="Nome legível para a categoria, ex: Atraso Logístico / Extravio")
    description: str = Field(description="Descrição da regra de negócio e escopo da categoria")
    keywords: list[str] = Field(description="Palavras-chave ou termos gatilho associados")

class TaxonomyDiscoveryOutput(BaseModel):
    """
    Saída estruturada da Fase 1 (Topic Modeling não-supervisionado).
    """
    categories: list[CategoryDefinition] = Field(description="Lista de 4 a 6 categorias mutuamente exclusivas descobertas")
    summary: str = Field(description="Resumo executivo do padrão de insatisfação detectado na amostra")

class ReviewClassification(BaseModel):
    """
    Contrato individual para classificação semântica de uma avaliação.
    """
    order_id: str = Field(description="ID único do pedido correspondente")
    categoria_primaria: str = Field(description="ID da categoria primária identificada (deve corresponder a um category_id da taxonomia)")
    motivo_especifico: str = Field(description="Resumo de até 15 palavras do motivo da queixa")
    severidade: str = Field(description="Nível de gravidade: 'alta', 'media' ou 'baixa'")
    reclamou_prazo: bool = Field(description="Indica se houve reclamação explícita de atraso ou prazo")
    reclamou_produto: bool = Field(description="Indica se houve reclamação de produto danificado, errado ou falsificado")
    reclamou_atendimento: bool = Field(description="Indica se houve reclamação de suporte, SAC ou falta de resposta")

class BatchClassificationOutput(BaseModel):
    """
    Envelope para classificação em lotes (batch processing).
    """
    classifications: list[ReviewClassification]


# --- Cliente e Integração com a Api do Google Genai ---

def get_gemini_client():
    """
    Inicializa o cliente oficial do Google GenAI a partir das variáveis de ambiente.
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        logger.error("FALHA CRÍTICA: 'API_KEY' não configurada no .env.")
        sys.exit(1)
    return genai.Client(api_key=api_key)


def test_llm_connection(client, model_name: str = None) -> str:
    """
    Valida a conexão com a API e seleciona um modelo disponível.
    """
    logger.info("Realizando Health Check de IA...")
    models_to_try = [model_name] if model_name else DEFAULT_MODELS

    last_error = None
    for model in models_to_try:
        try:
            response = client.models.generate_content(
                model=model,
                contents="Responda 'OK' se estiver online."
            )
            if response.text:
                logger.info(f"Health Check OK. Modelo ativo: '{model}'.")
                return model
        except Exception as e:
            logger.warning(f"Tentativa com modelo '{model}' falhou: {e}")
            last_error = e

    logger.error(f"FALHA CRÍTICA DE IA: Nenhum modelo disponível respondeu. Último erro: {last_error}")
    sys.exit(1)


# --- Extração, Descoberta e Classificação Semântica ---

def extract_reviews_from_dw(db_path: str = "data/processed/olist.duckdb", sample_size: int = 400) -> tuple[list[dict[str, any]], int]:
    """
    Extrai uma amostra aleatória de avaliações de detratores com texto preenchido.

    Retorna a amostra e o tamanho do universo elegível: sem o universo, o notebook não tem
    como declarar a margem de erro, e uma distribuição calculada sobre algumas centenas de
    avaliações aparenta precisão de censo.

    A amostragem usa reservoir com semente fixa, o que a torna aleatória e reproduzível.
    """
    if not os.path.exists(db_path):
        logger.error(f"Banco de dados '{db_path}' não encontrado. Execute o ETL antes da IA.")
        sys.exit(1)

    conn = duckdb.connect(db_path)
    filtro = f"""
        WHERE review_score <= {DETRACTOR_SCORE_MAX}
          AND review_comment_message IS NOT NULL
          AND TRIM(review_comment_message) != ''
    """

    universo = conn.execute(f"SELECT COUNT(*) FROM fato_pedidos {filtro}").fetchone()[0]

    df = conn.execute(f"""
        SELECT order_id, review_score, review_comment_message
        FROM fato_pedidos
        {filtro}
        USING SAMPLE {sample_size} ROWS (reservoir, {SAMPLE_SEED})
    """).df()
    conn.close()

    logger.info(f"Amostra de {len(df)} avaliações extraída de um universo de {universo} detratores.")
    return df.to_dict(orient="records"), universo


def discover_taxonomy(client, model: str, reviews_sample: list[dict[str, any]]) -> TaxonomyDiscoveryOutput:
    """
    Fase 1: Topic & Taxonomy Discovery.
    Minera uma amostra de reviews e descobre dinamicamente de 4 a 6 categorias de insatisfação.
    """
    logger.info("Fase 1: Executando Descoberta Dinâmica de Taxonomia (Topic Modeling via LLM)...")
    
    sample_text = "\n".join([f"- [Pedido {r['order_id']} | Nota {r['review_score']}]: {r['review_comment_message']}" for r in reviews_sample[:80]])
    
    prompt = f"""
    Você é um Lead Data & NLP Scientist especializado em E-Commerce e Marketplace.
    Abaixo está uma amostra aleatória de avaliações negativas (notas de 1 a {DETRACTOR_SCORE_MAX})
    de clientes reais.
    
    Sua missão é realizar uma DESCOBERTA DE TAXONOMIA NÃO SUPERVISIONADA:
    1. Analise o conjunto de textos e identifique entre 4 e 6 categorias macro MUTUAMENTE EXCLUSIVAS e EXAUSTIVAS que melhor agrupem todas as queixas.
    2. Evite categorias genéricas demais como 'Outros' ou 'Insatisfação Geral'.
    3. Crie identificadores padronizados em snake_case para cada categoria (ex: atraso_entrega, produto_divergente_incompleto, defeito_qualidade, falha_atendimento_sac).
    4. Forneça o nome legível, a descrição clara de enquadramento e as principais palavras-chave associadas.
    
    Amostra de Avaliações:
    {sample_text}
    """
    
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=TaxonomyDiscoveryOutput,
            temperature=0.2
        )
    )
    
    result = json.loads(response.text)
    taxonomy = TaxonomyDiscoveryOutput(**result)
    logger.info(f"Taxonomia descoberta com sucesso! {len(taxonomy.categories)} categorias identificadas:")
    for cat in taxonomy.categories:
        logger.info(f"  • [{cat.category_id}]: {cat.display_name}")
        
    return taxonomy


def classify_reviews_batch(client, model: str, reviews_data: list[dict[str, any]], taxonomy: TaxonomyDiscoveryOutput, batch_size: int = 50) -> list[ReviewClassification]:
    """
    Fase 2: Classificação Estruturada em Lotes.
    Classifica cada avaliação dentro da taxonomia descoberta com Structured Output estrito.
    """
    logger.info(f"Fase 2: Classificando {len(reviews_data)} avaliações em lotes de {batch_size}...")
    
    tax_prompt_desc = "\n".join([f"- {cat.category_id} ({cat.display_name}): {cat.description}" for cat in taxonomy.categories])
    valid_ids = [cat.category_id for cat in taxonomy.categories]
    
    all_classifications: list[ReviewClassification] = []
    falhas_no_lote = 0

    for i in range(0, len(reviews_data), batch_size):
        batch = reviews_data[i:i + batch_size]
        batch_text = "\n".join([f"- order_id: '{r['order_id']}' | review: '{r['review_comment_message']}'" for r in batch])
        
        prompt = f"""
        Você é um classificador analítico de Customer Experience. Classifique cada uma das seguintes avaliações na taxonomia abaixo.
        
        Taxonomia de Categorias Válidas:
        {tax_prompt_desc}
        
        IMPORTANTE: O campo 'categoria_primaria' DEVE ser EXATAMENTE um dos seguintes IDs válidos: {valid_ids}.
        
        Lote de Avaliações:
        {batch_text}
        """
        
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=BatchClassificationOutput,
                    temperature=0.1
                )
            )
            result = json.loads(response.text)
            batch_output = BatchClassificationOutput(**result)
            all_classifications.extend(batch_output.classifications)
            logger.info(f"  Progresso: {len(all_classifications)}/{len(reviews_data)} reviews classificados.")
        except Exception as e:
            logger.warning(f"Erro no processamento do lote {i // batch_size + 1}: {e}. Marcando lote como não classificado...")
            # Atribuir uma categoria da taxonomia a um lote que falhou seria pior do que não
            # classificar: os registros entrariam na distribuição como se fossem inferência.
            # Marcados assim, ficam identificáveis e são filtrados nas análises (ADR 015).
            falhas_no_lote += len(batch)
            for item in batch:
                comentario = item['review_comment_message'].lower()
                all_classifications.append(ReviewClassification(
                    order_id=item['order_id'],
                    categoria_primaria=CATEGORIA_NAO_CLASSIFICADA,
                    motivo_especifico="Falha na chamada ao modelo; registro não classificado",
                    severidade="indeterminada",
                    reclamou_prazo="prazo" in comentario or "atraso" in comentario,
                    reclamou_produto="produto" in comentario or "veio" in comentario,
                    reclamou_atendimento=False
                ))

    if falhas_no_lote:
        pct = 100.0 * falhas_no_lote / len(reviews_data)
        logger.warning(
            f"ATENÇÃO: {falhas_no_lote} de {len(reviews_data)} registros ({pct:.1f}%) não foram "
            f"classificados. Rode novamente antes de citar percentuais da taxonomia."
        )

    return all_classifications


# --- Persistência no DW ---

def persist_classifications_to_duckdb(classifications: list[ReviewClassification], db_path: str = "data/processed/olist.duckdb") -> None:
    """
    Fase 3: Persiste as classificações estruturadas na tabela 'fato_reviews_classificados' do DuckDB.
    """
    logger.info("Fase 3: Persistindo classificações no Data Warehouse DuckDB...")
    conn = duckdb.connect(db_path)

    # A tabela é recriada a cada execução, não acumulada: a taxonomia é redescoberta na
    # Fase 1, então rodadas diferentes geram rótulos distintos para o mesmo conceito e
    # misturá-las produziria uma média de taxonomias incompatíveis. O run_id rastreia qual
    # execução gerou cada linha (ADR 015).
    conn.execute("DROP TABLE IF EXISTS fato_reviews_classificados")
    conn.execute("""
        CREATE TABLE fato_reviews_classificados (
            order_id VARCHAR PRIMARY KEY,
            categoria_primaria VARCHAR,
            motivo_especifico VARCHAR,
            severidade VARCHAR,
            reclamou_prazo BOOLEAN,
            reclamou_produto BOOLEAN,
            reclamou_atendimento BOOLEAN,
            is_fallback BOOLEAN,
            run_id VARCHAR,
            data_classificacao TIMESTAMP
        )
    """)

    now = datetime.now()
    run_id = uuid.uuid4().hex[:12]
    records = [
        (
            c.order_id,
            c.categoria_primaria,
            c.motivo_especifico,
            c.severidade,
            c.reclamou_prazo,
            c.reclamou_produto,
            c.reclamou_atendimento,
            c.categoria_primaria == CATEGORIA_NAO_CLASSIFICADA,
            run_id,
            now,
        )
        for c in classifications
    ]

    conn.executemany("""
        INSERT OR REPLACE INTO fato_reviews_classificados
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)

    total_saved, total_fallback = conn.execute("""
        SELECT COUNT(*), COALESCE(SUM(CASE WHEN is_fallback THEN 1 ELSE 0 END), 0)
        FROM fato_reviews_classificados
    """).fetchone()
    conn.close()

    logger.info(
        f"Persistência concluída (run_id={run_id}). Registros: {total_saved} "
        f"({total_fallback} não classificados)."
    )


def run_ia_pipeline(sample_size: int = 400, db_path: str = "data/processed/olist.duckdb") -> None:
    """
    Orquestrador do pipeline de NLP e enriquecimento semântico.
    """
    logger.info("=== INICIANDO PIPELINE DE IA (NLP ENRICHMENT & DUCKDB) ===")
    
    client = get_gemini_client()
    active_model = test_llm_connection(client)
    
    # 1. Extração da base analítica
    reviews, universo = extract_reviews_from_dw(db_path=db_path, sample_size=sample_size)
    if not reviews:
        logger.warning("Nenhum review encontrado no Data Warehouse.")
        return
        
    # 2. Descoberta dinâmica de taxonomia
    taxonomy = discover_taxonomy(client, active_model, reviews)
    
    # 3. Classificação semântica em lote
    classifications = classify_reviews_batch(client, active_model, reviews, taxonomy, batch_size=50)
    
    # 4. Persistência no DW
    persist_classifications_to_duckdb(classifications, db_path=db_path)

    cobertura = 100.0 * len(reviews) / universo if universo else 0.0
    logger.info(
        f"=== PIPELINE DE IA CONCLUÍDO === Amostra de {len(reviews)} de {universo} detratores "
        f"({cobertura:.1f}% do universo)."
    )


if __name__ == "__main__":
    run_ia_pipeline()
