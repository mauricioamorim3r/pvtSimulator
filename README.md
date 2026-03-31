# SIMULPVT

Primeira entrega do projeto focada no modulo de Back-Flash.

## O que a app faz

- Le o catalogo de composicoes da planilha Bacalhau.
- Carrega casos internos de outubro/2025 e fevereiro/2026.
- Aceita upload de CSV/Excel para dados do separador.
- Permite ajustar Pressao/Temperatura do MPFM por slider ou ler P/T do proprio arquivo por linha.
- Aceita pressao em `bara` e tambem em `barg` nos arquivos operacionais, convertendo automaticamente para `bara`.
- Aceita cabecalhos em ingles ou portugues e tambem colunas de massa em `t`, convertendo automaticamente para `kg`.
- Calcula massas de referencia, K-factors, GOR e densidades com `NeqSim` real quando o backend estiver disponivel.
- Gera `Fe` e `Rs` a partir da fase oleo do separador, recalculando essa fase para `20 C / 1 atm`.
- Compara o modelo contra `volume de oleo do separador (CV)` e `densidade do oleo do separador (Coriolis)` quando esses dados vierem no arquivo.
- Mantem um modo `shadow` de contingencia caso a JVM ou o backend falhem.
- Possui modo de sensibilidade para comparar `GOR_337`, `GOR_351` e `GOR_393`.
- Exporta os resultados em CSV.

## Como rodar

```powershell
python -m streamlit run streamlit_app.py
```

## Windows rapido

Se voce estiver no Windows e nao quiser usar `Activate.ps1`, use os dois arquivos abaixo:

1. Execute [install_local.bat](/C:/PVT_M/SIMULPVT/install_local.bat)
2. Depois execute [run_local.bat](/C:/PVT_M/SIMULPVT/run_local.bat)

O instalador:

- usa `Python 3.13`
- cria `.venv`
- instala as dependencias
- tenta localizar `JAVA_HOME` automaticamente em `C:\Program Files\Eclipse Adoptium\jdk-*`
- valida o `NeqSim`

Isso evita o problema de tentar instalar `JPype1` com `Python 3.14`.

## Dicas de uso

- Se a planilha tiver `mpfm_pressure_bara` e `mpfm_temperature_c`, a app usa esses valores por linha e deixa o slider como fallback.
- Se a planilha tiver `separator_oil_volume_m3ph` e `separator_oil_density_kgm3`, a tela passa a mostrar a comparacao `CV` e `Coriolis` versus o modelo.
- A propria tela agora inclui um bloco "Passo a passo para o usuario" com orientacao da funcionalidade atual e das proximas entregas.

## Requisito para NeqSim real

O backend real do NeqSim exige Java JDK 11+ no `PATH` e `JAVA_HOME` configurado.

Passos esperados:

1. Instalar Java JDK 11 ou superior.
2. Configurar `JAVA_HOME`.
3. Garantir que `java -version` funcione no terminal.
4. Rodar novamente a app.

Sem isso, a interface continua funcionando em modo `shadow`.

## Observacao importante sobre Python

Para este pacote local, a trilha recomendada e testada e:

- `Python 3.13`
- `Java JDK 17`

Se voce tentar instalar com `Python 3.14`, o `pip` pode tentar compilar `JPype1` localmente e pedir `Microsoft Visual C++ Build Tools`.

## Preparacao para Render

O projeto agora inclui:

- [Dockerfile](/C:/PVT_M/SIMULPVT/Dockerfile)
- [render.yaml](/C:/PVT_M/SIMULPVT/render.yaml)
- [.dockerignore](/C:/PVT_M/SIMULPVT/.dockerignore)

O caminho recomendado para Render e via `Docker`, porque a app precisa de `Python + Java` para o `NeqSim`.

Fluxo esperado:

1. Subir este projeto para um repositorio Git
2. Conectar o repositorio ao Render
3. Criar um Web Service usando o [render.yaml](/C:/PVT_M/SIMULPVT/render.yaml)

Observacao: hoje esta pasta ainda nao e um repositorio Git, entao ela esta preparada para o Render, mas ainda nao pode ser publicada no Render ate entrar em um repo GitHub, GitLab ou Bitbucket.
