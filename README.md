**Projeto da disciplica Gestão da informação e do conhecimento**

**1. Introdução**

  Esta ontologia tem como objetivo modelar o domínio relacionado às áreas de conhecimento e à produção científica no estado de Pernambuco, considerando aspectos de quantidade e qualidade das publicações.
  O modelo foi construído com base nos conceitos de Ciência, Tecnologia e Inovação (CT&I), contemplando instituições, programas de pós-graduação, pesquisadores, produções científicas e indicadores associados.



**2. Conceitos**

  - Estado: unidade federativa analisada (Pernambuco).
  - ICT: instituições de ensino e pesquisa responsáveis pela produção científica.
  - PPG: programas de pós-graduação vinculados às ICTs.
  - Área de Conhecimento: domínio científico associado ao PPG e às produções.
  - Pesquisador (Autor): indivíduo responsável pela produção científica.
  - Produção Científica: resultados de pesquisa (artigos, teses, etc.).
  - Veículo de Publicação: meio de divulgação das produções.
  - Citação: métricas relacionadas ao impacto científico.


  
**3. Relações**
    
  - ICT localizada_em Estado
  - PPG sediado_em ICT
  - Pesquisador membro_de PPG
  - Produção Científica autoria Pesquisador
  - Produção Científica publicada_em Veículo de Publicação
  - Produção Científica classificada_em Área de Conhecimento
  - PPG associado_a Área de Conhecimento
  - Produção Científica mensurada_por Citação



**4. Propriedades**

  - Estado
    - nm_estado
    - sg_uf

  - ICT
    - cd_entidade_capes
    - nm_entidade_ensino
    - sg_entidade_ensino
    - sg_uf

  - PPG
    - cd_programa_ies
    - nm_programa_ies
    - nm_area_conhecimento
    - nm_modalidade_programa

  - Pesquisador (Autor)
    - ds_orc_id
    - ds_scopus_id
    - ds_url_google_scholar

  - Produção Científica
    - an_base_producao
    - ds_doi
    - ds_natureza
    - ds_palavras_chave
    - ds_url_acesso
    - nm_titulo
    - nr_citacoes_publicacao

  - Veículo de Publicação
    - ds_isbn_issn
    - nm_veiculo_publicacao
    - nr_citescore_scopus
    - nr_quartil_scopus

  - Citação
    - an_base_citacao
    - nr_citacoes_autor
    - nr_indice_h
    - nr_indice_i10

# Sprint 3 — Extração do Conhecimento

## Objetivo

A Sprint 3 tem como objetivo transformar a ontologia e as instâncias OML em conhecimento consultável por meio de RDF, Fuseki e consultas SPARQL.

O fluxo geral desta sprint é:

```text
OML → RDF/TTL → Fuseki → SPARQL → Resultados JSON

projetocti/
├── build.gradle
├── src/
│   ├── oml/
│   │   └── gic.ufrpe.br/
│   │       └── cti/
│   │           ├── vocabulary/
│   │           │   └── cti.oml
│   │           └── description/
│   │               └── cti-pe.oml
│   └── sparql/
│       ├── 01_evolucao_producao_por_ano.sparql
│       ├── 02_producoes_por_ict_e_area.sparql
│       ├── 03_qualidade_media_por_area.sparql
│       ├── 04_publicacoes_por_quartil.sparql
│       ├── 05_publica_vs_privada.sparql
│       ├── 06_impacto_pandemia_quantidade_qualidade.sparql
│       └── 07_top_veiculos_por_citescore.sparql