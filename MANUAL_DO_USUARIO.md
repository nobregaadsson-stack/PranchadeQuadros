# Prancha de Quadros — Manual do usuário

O aplicativo transforma um vídeo em **uma única imagem** com vários quadros organizados em grade, cada um
identificado pelo número e pelo tempo em que aparece no vídeo. Tudo é feito **no próprio computador**: o
vídeo não é enviado a lugar nenhum e o programa funciona sem internet.

---

## Passo a passo

### 1. Selecionar o vídeo

Clique em **Selecionar vídeo** (ou `Ctrl+O`) ou **arraste o arquivo** para a janela.
Formatos comuns: MP4, MOV, AVI, MKV, WEBM, WMV, MPG, TS/M2TS, 3GP e outros reconhecidos pelo FFmpeg.

O painel **Informações do arquivo** mostra nome, caminho (passe o mouse para ver completo), formato, codec,
duração, resolução, taxa de quadros, tamanho e datas do sistema de arquivos. O que não puder ser lido aparece
como **indisponível** — nada é estimado ou inventado.

Opcional: **Calcular SHA-256 do vídeo** registra a “impressão digital” dos bytes do arquivo naquele momento.

> O arquivo original é aberto apenas para leitura. O aplicativo também se recusa a gravar qualquer
> resultado com o mesmo nome/caminho do vídeo.

### 2. Navegar pelo vídeo

Controles do reprodutor:

| Botão / tecla | Ação |
|---|---|
| ▶ / ⏸ ou **Espaço** | reproduzir / pausar |
| **◀ 1 quadro** / **1 quadro ▶** ou **← / →** | quadro anterior / seguinte (exato) |
| **10 s** | retroceder / avançar 10 segundos |
| barra | ir para qualquer ponto |
| **Marcar início** / **Marcar fim** | usa a posição atual como início/fim do trecho |
| **Capturar quadro exibido** | acrescenta o quadro da tela à lista (seleção manual) |

Com o vídeo pausado, a imagem mostrada é decodificada pelo mesmo mecanismo da extração: o quadro que você vê
é exatamente o que será capturado, com o mesmo tempo.

### 3. Definir o trecho de análise

Em **Trecho de análise**, informe **Tempo inicial** e **Tempo final** (`HH:MM:SS`, `HH:MM:SS.mmm`, `MM:SS`
ou segundos). Nenhum quadro é gerado fora desse trecho.

### 4. Escolher o critério de extração

- **A — Intervalo de tempo:** um quadro a cada 1 s, 5 s, 10 s, 30 s, 1 min ou intervalo personalizado.
- **B — Quantidade de quadros:** 6, 12, 20, 30 ou quantidade personalizada, distribuídos uniformemente
  (incluindo o início e o fim do trecho, ou no centro de segmentos iguais).
- **C — Seleção manual:** use **Capturar quadro exibido** no reprodutor para cada momento desejado.

A linha abaixo informa quantos quadros serão extraídos. Marque **Acrescentar aos quadros já existentes** para
somar aos quadros da lista em vez de substituí-los.

### 5. Gerar os quadros

Clique em **Gerar quadros**. A barra de progresso, no rodapé, mostra a etapa e a contagem; **Cancelar**
interrompe com segurança (nada é acrescentado e o original não é tocado). Ao final, avisos informam quadros
que não puderam ser extraídos ou trechos danificados do arquivo.

### 6. Organizar os quadros

Na lista **Quadros selecionados** (a ordem da lista é a numeração na prancha):

- **Remover** (ou tecla `Delete`), **◀ Mover / Mover ▶** ou arrastar para reordenar;
- **Ordenar por tempo** restaura a ordem temporal;
- **Editar legenda** (ou duplo clique) corrige o texto de um quadro; deixar em branco volta à legenda automática;
- **Substituir…** troca o quadro por outro instante (pode usar a posição do reprodutor);
- **Acrescentar…** inclui um quadro de um instante digitado;
- **Ver no reprodutor** posiciona o reprodutor no quadro selecionado.

Passe o mouse sobre um quadro para ver o tempo solicitado e o tempo efetivo.

### 7. Montar e conferir a prancha

Aba **2 · Prancha e exportação**. A prévia no centro é a imagem final (zoom com `−`/`+`, **Ajustar**,
**100%** ou `Ctrl` + roda do mouse). Clique em um quadro da prévia para selecioná-lo na lista; duplo clique
edita a legenda. Abaixo da prévia aparecem as dimensões finais em pixels e em centímetros (no DPI escolhido).

**Modelos:**

| Modelo | Uso |
|---|---|
| Técnico simples | fundo branco, grade de 3 colunas, bordas discretas, número e tempo |
| Relatório investigativo | cabeçalho de identificação, 2 colunas, legendas maiores, margens amplas |
| Alta densidade | 6 colunas, quadros menores — vídeos longos ou sequências extensas |
| Personalizado | qualquer ajuste manual leva a este modelo |

**Restaurar layout padrão** volta ao “Técnico simples” mantendo os textos do cabeçalho.

Principais ajustes: colunas (botões 2/3/4/5 col. ou valor livre) ou número de linhas; dimensões da imagem
(pela largura de cada quadro — padrão 640 px, alta 1280 px, original do vídeo ou personalizada — ou dimensões
fixas como A4 300 dpi, Full HD, 4K ou personalizada, em retrato ou paisagem); ajuste do quadro (proporções
originais ou área padronizada com margens); alinhamento; espaçamentos; margens; borda; cores; posição,
formato e tamanho das legendas (opção de milissegundos); cabeçalho e nota de rodapé.

O formato da legenda aceita `{n}` (número) e `{tempo}` (tempo). Padrão: `QUADRO {n} — TEMPO: {tempo}`.

**Cabeçalho (opcional):** título, identificação do vídeo, nome do arquivo (preenchido), data e hora da análise
(preenchida com o relógio do computador — **confira**), procedimento/relatório/ocorrência, responsável,
intervalo analisado (preenchido automaticamente, editável) e observações. Só aparece o que estiver marcado e
preenchido. O aplicativo **não** insere brasões, logotipos, assinaturas ou selos.

**Nota de identificação (rodapé):** ativada por padrão, informa que a imagem é uma composição de quadros e não
uma reprodução integral do vídeo nem certificação de autenticidade. Pode ser editada ou desativada.

Se a prancha ficar grande demais, o aplicativo avisa e informa as dimensões; ele **nunca reduz a resolução
sozinho** — diminua a largura dos quadros, aumente as colunas ou reduza a quantidade de quadros.

### 8. Exportar

Em **Exportação**:

- **Formato:** PNG (recomendado, sem perdas) ou JPEG (arquivo menor; qualidade ajustável);
- **Gerar também versão PDF** (mesma imagem, no tamanho de página correspondente ao DPI);
- **Exportar quadros individuais (PNG):** pasta `<nome>_quadros` com `<nome>_quadro_01.png`, … — mesma
  numeração da prancha, pixels sem alteração;
- **Registro técnico** TXT e/ou CSV (abre no Excel, separador `;`);
- **Calcular SHA-256 do vídeo original** no momento da exportação.

Clique em **Exportar prancha…** e escolha pasta e nome. Ao final, a lista de arquivos gerados é exibida, com
o botão **Abrir pasta**. **Salvar somente o registro técnico…** grava o registro sem exportar a imagem.

---

## O registro técnico

Contém: arquivo de origem (nome, caminho, tamanho, datas, formato, codec, duração informada, resolução, taxa de
quadros, base de tempo), verificação de que o arquivo não mudou desde o carregamento, SHA-256 (quando
calculado, com data e contexto), critérios de extração, regra temporal, e para cada quadro: número, legenda,
origem, tempo solicitado, tempo efetivo, PTS, tipo de quadro, dimensões extraídas, posição/tamanho na prancha,
arquivo individual e SHA-256 — além do nome, dimensões e SHA-256 da prancha e da lista de eventos (extrações,
remoções, substituições, legendas editadas).

São **dados registrados pelo aplicativo**, não uma certificação automática de autenticidade do vídeo.

## Tempos: solicitado × efetivo

Um vídeo é uma sequência de quadros com duração própria (a 30 q/s, cada quadro dura ~0,033 s). Ao pedir o
instante 00:00:10.000, o aplicativo usa o quadro **em exibição** naquele instante; o tempo desse quadro
(tempo efetivo) é o que vai na legenda. Os dois tempos ficam no registro. A legenda mostra `HH:MM:SS`
truncado; ative os milissegundos quando a precisão for relevante.

## Mensagens de erro comuns

| Mensagem | O que fazer |
|---|---|
| “O arquivo não pôde ser reconhecido como vídeo” | o arquivo está corrompido, incompleto ou não é vídeo; obtenha uma cópia íntegra |
| “Não foi possível decodificar nenhum quadro… codec não suportado” | converta uma **cópia** do vídeo para MP4 (H.264) em outro programa |
| “O arquivo não contém trilha de vídeo” | o arquivo é só de áudio |
| “Reprodução contínua indisponível…” | apenas o reprodutor; use a barra e os botões de quadro — a extração funciona |
| “Os N quadros não cabem na imagem…” | aumente as dimensões fixas, reduza margens ou mude o número de colunas |
| “Sem permissão para gravar…” | feche o arquivo de destino em outros programas ou escolha outra pasta |

Erros inesperados são gravados em `%LOCALAPPDATA%\PranchaQuadros\erros.log`.

## Arquivos temporários

Os quadros extraídos ficam em uma pasta temporária local (`%TEMP%\prancha_quadros_*`), apagada ao fechar o
aplicativo ou ao carregar outro vídeo.
