import time
import os
import re
import json
import hashlib
import unicodedata
from pathlib import Path

import pandas as pd
import requests

# =============================
# CONFIGURAÇÕES
# =============================
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)
SCOPUS_RAW_DIR = OUTPUT_DIR / "scopus_raw"
OML_DESCRIPTION_DIR = Path("src/oml/gic.ufrpe.br/cti/description")
OML_DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
OML_GERADO_PATH = OML_DESCRIPTION_DIR / "cti-pe.oml"
OML_GERADO_IRI = "http://gic.ufrpe.br/cti/description/cti-pe#"
OML_GERADO_ALIAS = "cti-pe"
OML_COPIA_OUTPUT_PATH = OUTPUT_DIR / "instancias_pe.oml"
OML_COPIA_OUTPUT_IRI = "http://gic.ufrpe.br/cti/description/cti-pe-output#"
OML_COPIA_OUTPUT_ALIAS = "cti-pe-output"

PROGRAMAS_FILES = [
    DATA_DIR / "br-capes-colsucup-prog-2021-2025-03-31.csv",
    DATA_DIR / "br-capes-colsucup-prog-2022-2025-03-31.csv",
    DATA_DIR / "br-capes-colsucup-prog-2023-2025-03-31.csv",
    DATA_DIR / "br-capes-colsucup-prog-2024-2025-12-01.csv",
]

PRODUCAO_FILES = [
    DATA_DIR / "br-capes-colsucup-producao-2017a2020-2023-11-30-bibliografica-artpe_parte1.csv",
    DATA_DIR / "br-capes-colsucup-producao-2017a2020-2023-11-30-bibliografica-artpe_parte2.csv",
    DATA_DIR / "br-capes-colsucup-producao-2021a2024-2025-12-01-bibliografica-artpe-p1.csv",
    DATA_DIR / "br-capes-colsucup-producao-2021a2024-2025-12-01-bibliografica-artpe-p2.csv",
]

ANO_INICIAL, ANO_FINAL = 2017, 2024
COLUNA_AREA_CONHECIMENTO = "NM_AREA_CONHECIMENTO"


def carregar_env_local(caminho=".env"):
    """Carrega um .env simples sem exigir dependência externa."""
    env_path = Path(caminho)
    if not env_path.exists():
        return

    for linha in env_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip().strip('"').strip("'")
        if chave and chave not in os.environ:
            os.environ[chave] = valor


def env_bool(nome, padrao="0"):
    return os.getenv(nome, padrao).strip().lower() in {"1", "true", "sim", "yes", "y"}


def env_int(nome, padrao):
    try:
        return int(os.getenv(nome, str(padrao)).strip())
    except ValueError:
        return padrao


def env_float(nome, padrao):
    try:
        return float(os.getenv(nome, str(padrao)).strip().replace(",", "."))
    except ValueError:
        return padrao


carregar_env_local()

API_KEY_SCOPUS = os.getenv("SCOPUS_API_KEY", "").strip()
SCOPUS_INSTTOKEN = os.getenv("SCOPUS_INSTTOKEN", "").strip()
ATUALIZAR_SCOPUS = env_bool("ATUALIZAR_SCOPUS")
SCOPUS_FORCE_REFRESH = env_bool("SCOPUS_FORCE_REFRESH")
SCOPUS_SALVAR_RAW = env_bool("SCOPUS_SALVAR_RAW", "1")
SCOPUS_VIEW = os.getenv("SCOPUS_VIEW", "STANDARD").strip() or "STANDARD"
SCOPUS_FIELDS_METRICAS = os.getenv("SCOPUS_FIELDS_METRICAS", "").strip()
SCOPUS_TIMEOUT = env_int("SCOPUS_TIMEOUT", 30)
SCOPUS_MAX_RETRIES = env_int("SCOPUS_MAX_RETRIES", 3)
SCOPUS_INTERVALO_SEGUNDOS = env_float("SCOPUS_INTERVALO_SEGUNDOS", 0.25)

COLUNAS_SCOPUS = [
    "CD_IDENTIFICADOR_VEICULO",
    "ISSN_NORMALIZADO",
    "nm_veiculo_publicacao",
    "nr_citescore",
    "ds_quartil",
    "nr_snip",
    "status_consulta_scopus",
]

# Controles para teste. Use None nos dois campos para executar a base completa.
LIMITE_CONSULTAS_SCOPUS = None
LIMITE_REGISTROS_OML = None

MAPA_CATEGORIA = {
    "UFPE": "Pública",
    "UFRPE": "Pública",
    "UPE": "Pública",
    "UFAPE": "Pública",
    "UNIVASF": "Pública",
    "IFPE": "Pública",
    "IF SERTAO": "Pública",
    "IF SERTAO-PE": "Pública",
    "IFSERTAOPE": "Pública",
    "FIOCRUZ-NESC/CPQAM": "Pública",
    "ITEP": "Pública",
    "UNICAP": "Privada",
    "FPS": "Privada",
    "FADIC": "Privada",
    "IMIP": "Privada",
    "CESAR": "Privada",
    "UNIFBV-WYDEN": "Privada",
    "CERS": "Privada",
    "UNINASSAU": "Privada",
    "ESTACIO": "Privada",
    "UNIT": "Privada",
}


def get_tipo_ies(sigla):
    """Classifica a instituição sem assumir que toda desconhecida é privada."""
    sigla = str(sigla).strip().upper()
    return MAPA_CATEGORIA.get(sigla, "Não Classificada")


def limpar_nome_oml(texto, prefixo="id"):
    """Gera identificadores seguros para instâncias OML."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^A-Za-z0-9_]+", "_", texto).strip("_")
    if not texto:
        return f"{prefixo}_sem_valor"
    if texto[0].isdigit():
        return f"{prefixo}_{texto}"
    return texto


def escapar_string_oml(valor):
    """Escapa aspas e quebras de linha para não quebrar o arquivo OML."""
    if pd.isna(valor):
        return ""
    texto = str(valor)
    texto = texto.replace("\\", "\\\\")
    texto = texto.replace('"', '\\"')
    texto = texto.replace("\n", " ").replace("\r", " ")
    return texto.strip()


def normalizar_issn(issn):
    """
    Normaliza o identificador do veículo.
    Mantém apenas dígitos e X. Para a Scopus, normalmente precisamos de 8 caracteres.
    """
    if pd.isna(issn):
        return ""
    texto = str(issn).strip().upper()
    texto = re.sub(r"[^0-9X]", "", texto)
    return texto


def gerar_hash_curto(*valores):
    base = "|".join(escapar_string_oml(v) for v in valores)
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:10]


def parse_float(valor):
    """Converte valores de métricas bibliométricas para float, sem assumir zero."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        if pd.isna(valor):
            return None
        return float(valor)

    texto = str(valor).strip()
    if not texto or texto.lower() in {"none", "nan", "na", "n/a"}:
        return None

    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def parse_int(valor):
    numero = parse_float(valor)
    if numero is None:
        return None
    return int(numero)


def formatar_decimal(valor):
    numero = parse_float(valor)
    if numero is None:
        return ""

    texto = f"{numero:.6f}".rstrip("0").rstrip(".")
    return texto or "0"


def normalizar_lista(valor):
    if valor is None:
        return []
    if isinstance(valor, list):
        return valor
    return [valor]


def extrair_campo(registro, *chaves):
    if not isinstance(registro, dict):
        return None
    for chave in chaves:
        valor = registro.get(chave)
        if valor not in (None, ""):
            return valor
    return None


def primeiro_valor(valor):
    if isinstance(valor, list):
        for item in valor:
            if item not in (None, ""):
                return primeiro_valor(item)
        return None
    if isinstance(valor, dict):
        return extrair_campo(valor, "$", "#text", "value", "title", "dc:title")
    return valor


def extrair_metrica_mais_recente(entry, nome_metrica):
    """
    Extrai o valor mais recente de listas como SNIPList/SNIP.
    O JSON da API costuma representar cada item como {"@year": "2023", "$": "0.765"}.
    """
    lista_metricas = entry.get(f"{nome_metrica}List", {}) or {}
    if not isinstance(lista_metricas, dict):
        return "", ""

    registros = normalizar_lista(lista_metricas.get(nome_metrica))
    melhor_ano = None
    melhor_valor = None

    for registro in registros:
        ano = parse_int(extrair_campo(registro, "@year", "year", "@_year", "metricYear"))
        valor = parse_float(extrair_campo(
            registro,
            "$",
            "#text",
            "value",
            nome_metrica,
            nome_metrica.lower(),
            f"{nome_metrica}Value",
        ))

        if valor is None:
            continue

        if melhor_valor is None or melhor_ano is None or (ano is not None and ano > melhor_ano):
            melhor_ano = ano
            melhor_valor = valor

    return formatar_decimal(melhor_valor), str(melhor_ano or "")


def extrair_citescore(entry):
    cite_info = entry.get("citeScoreYearInfoList", {}) or {}
    if not isinstance(cite_info, dict):
        return "", "", ""

    cite_score = extrair_campo(
        cite_info,
        "citeScoreCurrentMetric",
        "citeScoreTracker",
        "citeScore",
        "CiteScore",
    )
    ano = extrair_campo(
        cite_info,
        "citeScoreCurrentMetricYear",
        "citeScoreTrackerYear",
        "@year",
        "year",
    )
    percentil = extrair_campo(
        cite_info,
        "citeScoreCurrentMetricPercentile",
        "citeScoreCurrentMetricPercentileRank",
        "citeScoreHighestPercentile",
        "percentile",
    )

    registros = normalizar_lista(cite_info.get("citeScoreYearInfo"))
    for registro in registros:
        valor_registro = extrair_campo(
            registro,
            "citeScore",
            "citeScoreValue",
            "citeScoreCurrentMetric",
            "$",
            "#text",
            "value",
        )
        ano_registro = extrair_campo(registro, "@year", "year", "metricYear")
        percentil_registro = extrair_campo(
            registro,
            "citeScoreCurrentMetricPercentile",
            "citeScorePercentile",
            "percentile",
        )

        if parse_float(valor_registro) is None:
            continue

        ano_atual = parse_int(ano)
        ano_novo = parse_int(ano_registro)
        if not cite_score or (ano_novo is not None and (ano_atual is None or ano_novo >= ano_atual)):
            cite_score = valor_registro
            ano = ano_registro
            if percentil_registro:
                percentil = percentil_registro

    return formatar_decimal(cite_score), str(ano or ""), formatar_decimal(percentil)


def extrair_titulo_veiculo(entry):
    titulo = extrair_campo(
        entry,
        "dc:title",
        "prism:publicationName",
        "publicationName",
        "sourceTitle",
        "title",
    )
    return escapar_string_oml(primeiro_valor(titulo))


def classificar_quartil_por_percentil(percentil_raw):
    percentil = parse_float(percentil_raw)
    if percentil is None:
        return "Quartil_Indisponivel"

    if percentil >= 75:
        return "Q1"
    if percentil >= 50:
        return "Q2"
    if percentil >= 25:
        return "Q3"
    return "Q4"


def metricas_scopus_vazias(status, quartil="Quartil_Indisponivel"):
    return {
        "nm_veiculo_publicacao": "",
        "nr_citescore": "",
        "ds_quartil": quartil,
        "nr_snip": "",
        "status_consulta_scopus": status,
    }


def montar_metricas_scopus(entry):
    titulo = extrair_titulo_veiculo(entry)
    cite_score, _ano_citescore, percentil = extrair_citescore(entry)
    snip, _ano_snip = extrair_metrica_mais_recente(entry, "SNIP")

    if cite_score and snip:
        status = "ok"
    elif cite_score:
        status = "ok_sem_snip"
    elif snip:
        status = "ok_sem_citescore"
    else:
        status = "ok_sem_metricas"

    metricas = {
        "nm_veiculo_publicacao": titulo,
        "nr_citescore": cite_score,
        "ds_quartil": classificar_quartil_por_percentil(percentil),
        "nr_snip": snip,
        "status_consulta_scopus": status,
    }
    return metricas


def tem_valor_metrica(row, coluna):
    valor = row.get(coluna, "")
    if pd.isna(valor):
        return False
    return str(valor).strip().lower() not in {"", "nan", "none"}


def precisa_atualizar_metricas(row):
    """
    Reconsulta caches antigos que ainda não tinham CiteScore ou SNIP.
    ISSNs inválidos e 404 são mantidos para não repetir consultas inúteis.
    """
    status = str(row.get("status_consulta_scopus", "")).strip().lower()
    if status in {"sem_issn", "issn_invalido", "ok_sem_metricas"} or status.startswith("http_404"):
        return False

    if status == "ok_sem_snip":
        return not tem_valor_metrica(row, "nr_snip")

    if status == "ok_sem_citescore":
        return not tem_valor_metrica(row, "nr_citescore")

    return not tem_valor_metrica(row, "nr_citescore") or not tem_valor_metrica(row, "nr_snip")


def usar_cache_scopus(df_veiculos, df_existente):
    """
    Retorna todos os veículos da base, enriquecidos apenas quando há cache.
    Não escreve registros artificiais no cache para veículos ainda não consultados.
    """
    metric_cols = [coluna for coluna in COLUNAS_SCOPUS if coluna != "CD_IDENTIFICADOR_VEICULO"]
    df_cache = df_existente[metric_cols].drop_duplicates(subset=["ISSN_NORMALIZADO"], keep="last")
    df_enriquecido = df_veiculos.merge(df_cache, on="ISSN_NORMALIZADO", how="left")

    for coluna in COLUNAS_SCOPUS:
        if coluna not in df_enriquecido.columns:
            df_enriquecido[coluna] = ""

    df_enriquecido["ds_quartil"] = (
        df_enriquecido["ds_quartil"]
        .fillna("")
        .replace("", "Quartil_Indisponivel")
    )
    return df_enriquecido[COLUNAS_SCOPUS]


def escrever_decimal_oml(f, propriedade, valor):
    valor_formatado = formatar_decimal(valor)
    if valor_formatado:
        f.write(f"    cti:{propriedade} {valor_formatado}\n")


# =============================
# LEITURA DOS CSVs
# =============================
def ler_arquivos(lista):
    dfs = []
    for arquivo in lista:
        if not arquivo.exists():
            print(f"Aviso: arquivo não encontrado: {arquivo}")
            continue
        print(f"Lendo {arquivo.name}")
        df = pd.read_csv(arquivo, sep=";", encoding="latin1", dtype=str, low_memory=False)
        df["__arquivo_origem"] = arquivo.name
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError("Nenhum arquivo CSV foi encontrado. Verifique a pasta data/.")

    return pd.concat(dfs, ignore_index=True)


# =============================
# SCOPUS
# =============================
def montar_headers_scopus(api_key):
    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
    }
    if SCOPUS_INSTTOKEN:
        headers["X-ELS-Insttoken"] = SCOPUS_INSTTOKEN
    return headers


def esperar_retry_scopus(response, tentativa):
    reset = response.headers.get("X-RateLimit-Reset")
    espera = min(60, 2 ** tentativa)

    if response.status_code == 429 and reset:
        try:
            espera = max(espera, min(600, int(reset) - int(time.time()) + 1))
        except ValueError:
            pass

    print(f"Scopus retornou HTTP {response.status_code}. Nova tentativa em {espera}s.")
    time.sleep(espera)


def consultar_endpoint_scopus(url, params, api_key):
    headers = montar_headers_scopus(api_key)
    for tentativa in range(SCOPUS_MAX_RETRIES + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=SCOPUS_TIMEOUT)
        except requests.RequestException as erro:
            if tentativa >= SCOPUS_MAX_RETRIES:
                raise
            espera = min(60, 2 ** tentativa)
            print(f"Erro de requisição na Scopus ({erro}). Nova tentativa em {espera}s.")
            time.sleep(espera)
            continue

        if response.status_code in {429, 500, 502, 503, 504} and tentativa < SCOPUS_MAX_RETRIES:
            esperar_retry_scopus(response, tentativa)
            continue

        return response

    return response


def extrair_entries_scopus(data):
    resposta = data.get("serial-metadata-response", {}) if isinstance(data, dict) else {}
    return normalizar_lista(resposta.get("entry", []))


def escolher_melhor_entry(entries):
    melhor_entry = None
    melhor_score = -1

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        metricas = montar_metricas_scopus(entry)
        score = sum(1 for coluna in ["nm_veiculo_publicacao", "nr_citescore", "nr_snip"] if metricas.get(coluna))

        if score > melhor_score:
            melhor_entry = entry
            melhor_score = score

    return melhor_entry or (entries[0] if entries else None)


def salvar_raw_scopus(issn, data):
    if not SCOPUS_SALVAR_RAW:
        return

    SCOPUS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    caminho = SCOPUS_RAW_DIR / f"{issn}.json"
    caminho.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def buscar_metricas_scopus(issn, api_key):
    """
    Consulta métricas da Scopus para um ISSN.
    Retorna CiteScore, quartil quando disponível e SNIP via view STANDARD.
    """
    issn_clean = normalizar_issn(issn)

    if not issn_clean:
        return metricas_scopus_vazias("sem_issn", "Sem_ISSN")

    if len(issn_clean) != 8:
        return metricas_scopus_vazias("issn_invalido", "ISSN_Invalido")

    if not api_key:
        return metricas_scopus_vazias("api_key_ausente", "Nao_Consultado")

    tentativas_endpoint = [
        (
            f"https://api.elsevier.com/content/serial/title/issn/{issn_clean}",
            {"view": SCOPUS_VIEW},
            "issn_path",
        ),
        (
            "https://api.elsevier.com/content/serial/title",
            {"issn": issn_clean, "view": SCOPUS_VIEW},
            "issn_query",
        ),
    ]
    if SCOPUS_FIELDS_METRICAS:
        for _, params, _ in tentativas_endpoint:
            params["field"] = SCOPUS_FIELDS_METRICAS

    ultimo_status = None

    for url, params, endpoint_nome in tentativas_endpoint:
        try:
            response = consultar_endpoint_scopus(url, params, api_key)
        except requests.RequestException as erro:
            print(f"Erro de requisição na Scopus para ISSN {issn}: {erro}")
            return metricas_scopus_vazias("erro_requisicao")

        ultimo_status = response.status_code
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            return metricas_scopus_vazias(f"http_{response.status_code}")

        try:
            data = response.json()
        except ValueError:
            return metricas_scopus_vazias("json_invalido")

        salvar_raw_scopus(issn_clean, data)
        entries = extrair_entries_scopus(data)
        if not entries:
            continue

        entry = escolher_melhor_entry(entries)
        metricas = montar_metricas_scopus(entry)
        return metricas

    if ultimo_status == 404:
        return metricas_scopus_vazias("http_404")
    return metricas_scopus_vazias("sem_entry")


def gerar_veiculos_enriquecidos(df_final):
    """
    1. Extrai veículos distintos.
    2. Salva veiculos_distintos.csv.
    3. Consulta Scopus uma vez por veículo.
    4. Salva veiculos_enriquecidos_scopus.csv.
    """
    veiculos_path = OUTPUT_DIR / "veiculos_distintos.csv"
    enriquecidos_path = OUTPUT_DIR / "veiculos_enriquecidos_scopus.csv"

    df_veiculos = df_final[["CD_IDENTIFICADOR_VEICULO"]].drop_duplicates().copy()
    df_veiculos["CD_IDENTIFICADOR_VEICULO"] = df_veiculos["CD_IDENTIFICADOR_VEICULO"].fillna("").astype(str).str.strip()
    df_veiculos = df_veiculos[df_veiculos["CD_IDENTIFICADOR_VEICULO"] != ""]
    df_veiculos["ISSN_NORMALIZADO"] = df_veiculos["CD_IDENTIFICADOR_VEICULO"].apply(normalizar_issn)
    df_veiculos = df_veiculos.drop_duplicates(subset=["ISSN_NORMALIZADO"])

    df_veiculos.to_csv(veiculos_path, index=False, encoding="utf-8-sig")
    print(f"Veículos distintos gerados: {len(df_veiculos)} -> {veiculos_path}")

    # Cache: se já existe arquivo enriquecido, reaproveita e consulta só os faltantes.
    if enriquecidos_path.exists():
        df_existente = pd.read_csv(enriquecidos_path, dtype=str, encoding="utf-8-sig")
        for coluna in COLUNAS_SCOPUS:
            if coluna not in df_existente.columns:
                df_existente[coluna] = ""
        df_existente["ds_quartil"] = (
            df_existente["ds_quartil"]
            .fillna("")
            .replace("", "Quartil_Indisponivel")
        )
        df_existente = df_existente[COLUNAS_SCOPUS]
        if SCOPUS_FORCE_REFRESH:
            ja_consultados = set()
        else:
            ja_consultados = set(
                df_existente[~df_existente.apply(precisa_atualizar_metricas, axis=1)]["ISSN_NORMALIZADO"]
                .dropna()
                .astype(str)
            )
        print(f"Cache encontrado com {len(df_existente)} veículos já enriquecidos.")
    else:
        df_existente = pd.DataFrame(columns=COLUNAS_SCOPUS)
        ja_consultados = set()

    if not ATUALIZAR_SCOPUS:
        print(
            "Atualização Scopus desativada. "
            "Usando métricas já presentes em output/veiculos_enriquecidos_scopus.csv."
        )
        return usar_cache_scopus(df_veiculos, df_existente)

    if not API_KEY_SCOPUS:
        print(
            "ATUALIZAR_SCOPUS está ativo, mas SCOPUS_API_KEY não foi definida. "
            "Usando somente o cache existente."
        )
        return usar_cache_scopus(df_veiculos, df_existente)

    if SCOPUS_FORCE_REFRESH:
        print("Reconsulta completa ativada: todos os ISSNs válidos serão consultados novamente.")
    if SCOPUS_SALVAR_RAW:
        print(f"JSON bruto da Scopus será salvo em: {SCOPUS_RAW_DIR}")
    print(
        "Parâmetros Scopus: "
        f"view={SCOPUS_VIEW}, intervalo={SCOPUS_INTERVALO_SEGUNDOS}s, "
        f"timeout={SCOPUS_TIMEOUT}s, retries={SCOPUS_MAX_RETRIES}."
    )

    novos_resultados = []
    pendentes = df_veiculos[~df_veiculos["ISSN_NORMALIZADO"].isin(ja_consultados)].copy()
    total_pendentes = len(pendentes)

    if LIMITE_CONSULTAS_SCOPUS is not None:
        pendentes = pendentes.head(LIMITE_CONSULTAS_SCOPUS).copy()
        print(
            "Modo teste Scopus ativo: "
            f"serão consultados {len(pendentes)} de {total_pendentes} veículos pendentes."
        )
    else:
        print(f"Veículos pendentes para consulta Scopus: {total_pendentes}")

    for consulta_idx, (idx, row) in enumerate(pendentes.iterrows(), start=1):
        issn_original = row["CD_IDENTIFICADOR_VEICULO"]
        issn_norm = row["ISSN_NORMALIZADO"]

        metricas = buscar_metricas_scopus(issn_norm, API_KEY_SCOPUS)

        resultado = {
            "CD_IDENTIFICADOR_VEICULO": issn_original,
            "ISSN_NORMALIZADO": issn_norm,
        }
        resultado.update(metricas)
        novos_resultados.append(resultado)

        # Salva parcialmente a cada 100 consultas para não perder tudo se interromper.
        if len(novos_resultados) % 100 == 0:
            df_tmp = pd.concat([df_existente, pd.DataFrame(novos_resultados)], ignore_index=True)
            df_tmp = df_tmp.drop_duplicates(subset=["ISSN_NORMALIZADO"], keep="last")
            df_tmp = df_tmp[COLUNAS_SCOPUS]
            df_tmp.to_csv(enriquecidos_path, index=False, encoding="utf-8-sig")
            print(
                f"Progresso salvo: {len(novos_resultados)} novas consultas "
                f"({consulta_idx}/{len(pendentes)} pendentes desta execução)."
            )

        time.sleep(SCOPUS_INTERVALO_SEGUNDOS)

    if novos_resultados:
        df_novos = pd.DataFrame(novos_resultados)
        df_enriquecido = pd.concat([df_existente, df_novos], ignore_index=True)
        df_enriquecido = df_enriquecido.drop_duplicates(subset=["ISSN_NORMALIZADO"], keep="last")
    else:
        df_enriquecido = df_existente

    for coluna in COLUNAS_SCOPUS:
        if coluna not in df_enriquecido.columns:
            df_enriquecido[coluna] = ""
    df_enriquecido["ds_quartil"] = (
        df_enriquecido["ds_quartil"]
        .fillna("")
        .replace("", "Quartil_Indisponivel")
    )
    df_enriquecido = df_enriquecido[COLUNAS_SCOPUS]
    df_enriquecido.to_csv(enriquecidos_path, index=False, encoding="utf-8-sig")
    print(f"Veículos enriquecidos gerados: {len(df_enriquecido)} -> {enriquecidos_path}")
    if LIMITE_CONSULTAS_SCOPUS is not None and total_pendentes > len(pendentes):
        print(
            "Teste Scopus concluído. "
            f"Restam {total_pendentes - len(pendentes)} veículos pendentes para uma execução completa."
        )

    return df_enriquecido


# =============================
# GERAÇÃO OML
# =============================
def gerar_oml_final(df):
    output_path = OML_GERADO_PATH

    if LIMITE_REGISTROS_OML is not None:
        df_oml = df.head(LIMITE_REGISTROS_OML).copy()
        print(f"Gerando OML com amostra de {len(df_oml)} registros.")
    else:
        df_oml = df.copy()
        print(f"Gerando OML com todos os {len(df_oml)} registros.")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"description <{OML_GERADO_IRI}> as {OML_GERADO_ALIAS} {{\n\n")
        f.write("  uses <http://gic.ufrpe.br/cti/vocabulary/cti#> as cti\n\n")

        ies_processadas = set()
        ppgs_processados = set()
        areas_processadas = set()
        veiculos_processados = set()
        producoes_processadas = set()

        for i, row in df_oml.iterrows():
            sigla_ies = escapar_string_oml(row.get("SG_ENTIDADE_ENSINO", ""))
            id_ict = limpar_nome_oml(f"ict_{sigla_ies}", "ict")

            id_ppg_base = limpar_nome_oml(row.get("CD_PROGRAMA_IES", ""), "ppg")
            id_ppg = f"ppg_{id_ppg_base}"

            id_area_base = limpar_nome_oml(row.get(COLUNA_AREA_CONHECIMENTO, ""), "area")
            id_area = f"area_{id_area_base}"

            issn_norm = escapar_string_oml(row.get("ISSN_NORMALIZADO", ""))
            id_veiculo = f"veiculo_{limpar_nome_oml(issn_norm, 'veiculo')}"

            # A produção passa a ter ID estável baseado em título, ano e veículo.
            hash_prod = gerar_hash_curto(
                row.get("NM_PRODUCAO", ""),
                row.get("AN_BASE", ""),
                row.get("CD_IDENTIFICADOR_VEICULO", ""),
                row.get("CD_PROGRAMA_IES", ""),
            )
            id_prod = f"prod_{hash_prod}"

            # 1. Instância Área de Conhecimento
            if id_area not in areas_processadas:
                f.write(f"  instance {id_area} : cti:Area_Conhecimento [\n")
                f.write(f'    cti:nm_area_conhecimento "{escapar_string_oml(row.get(COLUNA_AREA_CONHECIMENTO, ""))}"\n')
                f.write("  ]\n\n")
                areas_processadas.add(id_area)

            # 2. Instância ICT
            if id_ict not in ies_processadas:
                f.write(f"  instance {id_ict} : cti:ICT [\n")
                f.write(f'    cti:sg_entidade_ensino "{sigla_ies}"\n')
                f.write(f'    cti:ds_dependencia_administrativa "{get_tipo_ies(sigla_ies)}"\n')
                f.write("  ]\n\n")
                ies_processadas.add(id_ict)

            # 3. Instância PPG
            if id_ppg not in ppgs_processados:
                f.write(f"  instance {id_ppg} : cti:PPG [\n")
                f.write(f'    cti:nm_programa_ies "{escapar_string_oml(row.get("NM_PROGRAMA_IES", ""))}"\n')
                f.write(f"    cti:sediado_em {id_ict}\n")
                f.write(f"    cti:pertence {id_area}\n")
                f.write("  ]\n\n")
                ppgs_processados.add(id_ppg)

            # 4. Instância Veículo de Publicação
            if id_veiculo not in veiculos_processados:
                f.write(f"  instance {id_veiculo} : cti:Veiculo_Publicacao [\n")
                f.write(f'    cti:cd_identificador_veiculo "{escapar_string_oml(row.get("CD_IDENTIFICADOR_VEICULO", ""))}"\n')
                nome_veiculo = escapar_string_oml(row.get("nm_veiculo_publicacao", ""))
                if nome_veiculo:
                    f.write(f'    cti:nm_veiculo_publicacao "{nome_veiculo}"\n')
                escrever_decimal_oml(f, "nr_citescore", row.get("nr_citescore", ""))
                escrever_decimal_oml(f, "nr_snip", row.get("nr_snip", ""))
                f.write(f'    cti:ds_quartil "{escapar_string_oml(row.get("ds_quartil", "Sem_Quartil"))}"\n')
                f.write("  ]\n\n")
                veiculos_processados.add(id_veiculo)

            # 5. Instância Produção Científica
            if id_prod not in producoes_processadas:
                f.write(f"  instance {id_prod} : cti:Producao_Cientifica [\n")
                f.write(f'    cti:nm_producao "{escapar_string_oml(row.get("NM_PRODUCAO", ""))}"\n')
                f.write(f'    cti:an_base {int(row["AN_BASE"])}\n')
                f.write(f"    cti:vinculada {id_ppg}\n")
                f.write(f"    cti:publicada_em {id_veiculo}\n")
                f.write("  ]\n\n")
                producoes_processadas.add(id_prod)

        f.write("}")

    print(f"OML gerado em: {output_path}")

    conteudo_oml = output_path.read_text(encoding="utf-8")
    conteudo_oml = conteudo_oml.replace(
        f"description <{OML_GERADO_IRI}> as {OML_GERADO_ALIAS} {{",
        f"description <{OML_COPIA_OUTPUT_IRI}> as {OML_COPIA_OUTPUT_ALIAS} {{",
        1,
    )
    OML_COPIA_OUTPUT_PATH.write_text(conteudo_oml, encoding="utf-8")
    print(f"Cópia OML gerada em: {OML_COPIA_OUTPUT_PATH}")


# =============================
# PIPELINE PRINCIPAL
# =============================
def main():
    df_prog = ler_arquivos(PROGRAMAS_FILES)
    df_prod = ler_arquivos(PRODUCAO_FILES)

    # 1. Filtro Programas (PE)
    df_prog = df_prog[df_prog["SG_UF_PROGRAMA"] == "PE"][[
        "CD_PROGRAMA_IES",
        "NM_PROGRAMA_IES",
        "SG_ENTIDADE_ENSINO",
        COLUNA_AREA_CONHECIMENTO,
    ]].drop_duplicates()

    # 2. Filtro Produção
    df_prod["AN_BASE"] = pd.to_numeric(df_prod["AN_BASE"], errors="coerce")
    df_prod = df_prod[(df_prod["AN_BASE"] >= ANO_INICIAL) & (df_prod["AN_BASE"] <= ANO_FINAL)]
    df_prod = df_prod[[
        "CD_PROGRAMA_IES",
        "AN_BASE",
        "NM_PRODUCAO",
        "CD_IDENTIFICADOR_VEICULO",
    ]]

    # 3. Integração CAPES: produção + programa
    df_final = df_prod.merge(df_prog, on="CD_PROGRAMA_IES", how="inner")
    print(f"Registros integrados antes da deduplicação: {len(df_final)}")

    # 4. Remoção de duplicatas de produção
    df_final = df_final.drop_duplicates(
        subset=["NM_PRODUCAO", "AN_BASE", "CD_IDENTIFICADOR_VEICULO", "CD_PROGRAMA_IES"]
    ).copy()
    print(f"Registros integrados depois da deduplicação: {len(df_final)}")

    # 5. Salva base consolidada sem métricas
    df_final.to_csv(OUTPUT_DIR / "df_final_capes_deduplicado.csv", index=False, encoding="utf-8-sig")

    # 6. Extrai veículos únicos e consulta Scopus uma vez por veículo
    df_veiculos = gerar_veiculos_enriquecidos(df_final)

    # 7. Junta métricas dos veículos de volta na base final
    df_final["ISSN_NORMALIZADO"] = df_final["CD_IDENTIFICADOR_VEICULO"].apply(normalizar_issn)
    colunas_scopus_merge = [
        "ISSN_NORMALIZADO",
        "nm_veiculo_publicacao",
        "nr_citescore",
        "ds_quartil",
        "nr_snip",
    ]
    df_final = df_final.merge(
        df_veiculos[colunas_scopus_merge],
        on="ISSN_NORMALIZADO",
        how="left",
    )
    df_final["ds_quartil"] = (
        df_final["ds_quartil"]
        .fillna("")
        .replace("", "Quartil_Indisponivel")
    )

    # 8. Salva base consolidada final com métricas por veículo
    df_final.to_csv(OUTPUT_DIR / "df_final_capes_scopus.csv", index=False, encoding="utf-8-sig")
    print(f"Base final CAPES + Scopus salva em: {OUTPUT_DIR / 'df_final_capes_scopus.csv'}")

    # 9. Gera OML com Veiculo_Publicacao e relação publicada_em
    gerar_oml_final(df_final)


if __name__ == "__main__":
    main()
