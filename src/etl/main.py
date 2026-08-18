"""
Módulo Principal de Orquestração (Pipeline ETL/ELT)

Responsável pelo fluxo do projeto:
1. Ingestão híbrida dos dados brutos (KaggleHub com fallback local - ADR 006).
2. Validação e saneamento na camada Staging com política de soft fail (ADR 003 e 005).
3. Execução das transformações para estruturação do Star Schema no DuckDB (ADR 004).
"""

import duckdb
import logging
import os
import kagglehub

from src.dq.validators import run_dq_pipeline

# Configuração de logging padronizado para rastreabilidade de execução
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def download_raw_data(raw_dir: str = "data/raw") -> bool:
    """
    Realiza a ingestão dos dados brutos aplicando estratégia híbrida resiliente.
    
    Tenta o download automático via API do KaggleHub; caso ocorra indisponibilidade
    de rede ou ausência de credenciais, utiliza os arquivos em data/raw/ como fallback.
    """
    if not os.path.exists(raw_dir):
        os.makedirs(raw_dir)
    
    required_file = os.path.join(raw_dir, "olist_orders_dataset.csv")
    
    logger.info("Obtenção de dados via kagglehub ...")
    try:
        # Download automático para cache local gerenciado pelo KaggleHub
        cache_path = kagglehub.dataset_download("olistbr/brazilian-ecommerce")
        
        logger.info("Movendo arquivos do cache para o diretório analítico local...")
        for file_name in os.listdir(cache_path):
            if file_name.endswith(".csv"):
                src = os.path.join(cache_path, file_name)
                dst = os.path.join(raw_dir, file_name)
                with open(src, 'rb') as f_in, open(dst, 'wb') as f_out:
                    f_out.write(f_in.read())
                    
        logger.info("Download e sincronização via Kaggle finalizados com sucesso!")
        return True
    except Exception as e:
        logger.warning(f"Falha na integração com o Kaggle: {e}. Verificando fallback local...")
        if os.path.exists(required_file):
            logger.info("Fallback acionado: Arquivos brutos já localizados em data/raw/. Prosseguindo com os dados locais.")
            return True
        else:
            logger.error("Falha ao obter dados via Kaggle e nenhum arquivo bruto local foi encontrado em data/raw/.")
            return False


def execute_sql_pipeline(sql_file_path: str, db_path: str = "data/processed/olist.duckdb") -> None:
    """
    Executa o script DDL/DML no DuckDB in-process, gerando o Star Schema analítico.
    """
    logger.info(f"Conectando ao banco analítico local em {db_path}...")
    
    db_dir = os.path.dirname(db_path)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)

    conn = duckdb.connect(db_path)
    
    with open(sql_file_path, 'r', encoding='utf-8') as f:
        sql_commands = f.read()
        
    logger.info("Executando modelagem (criando Star Schema)...")
    conn.execute(sql_commands)
    
    logger.info("Modelagem concluída com sucesso! Banco disponível para análises.")
    conn.close()


def main() -> None:
    """
    Orquestra sequencialmente as 3 etapas da esteira de engenharia de dados.
    """
    logger.info("--- Iniciando Pipeline ETL (Olist Case) ---")
    
    # 1. Ingestão Híbrida
    if not download_raw_data():
        logger.error("Falha ao preparar o ambiente de dados. Interrompendo pipeline.")
        return
        
    # 2. Suíte de Qualidade de Dados (Soft Fail: isola anomalias para quarentena e popula staging)
    run_dq_pipeline()

    # 3. Modelagem Dimensional (Lê dados de staging e consolida fatos/dimensões no DuckDB)
    sql_path = os.path.join("sql", "star_schema.sql")
    if not os.path.exists(sql_path):
        logger.error(f"Script de modelagem SQL não encontrado: {sql_path}")
        return
        
    execute_sql_pipeline(sql_path)
    logger.info("--- Pipeline ETL Finalizado com Sucesso ---")


if __name__ == "__main__":
    main()
