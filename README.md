# Prancha de Quadros

Aplicativo desktop **offline**, em português, para extrair quadros de arquivos de vídeo e compor
automaticamente uma **prancha visual** (uma única imagem em grade, com identificação temporal de cada
quadro) pronta para relatórios técnicos, investigativos e documentais.

- Todo o processamento é local: nenhum arquivo, metadado ou informação é enviado pela internet; não há
  conta, cadastro nem telemetria.
- O vídeo original é aberto **somente para leitura** e nunca é sobrescrito.
- A prévia e a imagem exportada são geradas pela mesma rotina: o PNG é idêntico, pixel a pixel, ao que se vê.
- O registro técnico (TXT/CSV) documenta tempos solicitados e efetivos, PTS, critérios e SHA-256.

Manual de uso: [docs/MANUAL_DO_USUARIO.md](docs/MANUAL_DO_USUARIO.md).

---

## 1. Para quem só vai usar (executável)

1. Copie a pasta `PranchaQuadros` (ou descompacte `PranchaQuadros-1.0.0-win64.zip`) para qualquer local,
   por exemplo `C:\Programas\PranchaQuadros`.
2. Execute `PranchaQuadros.exe`.

Não é necessário instalar Python, FFmpeg nem qualquer outra ferramenta: tudo vai dentro da pasta. Não há
instalador nem gravação no registro do Windows além da lembrança das últimas pastas usadas
(`HKCU\Software\PranchaQuadros`).

Requisitos: Windows 10 ou 11 de 64 bits. Recomenda-se 8 GB de RAM para pranchas grandes.

Para verificar a instalação em uma máquina (inclusive sem internet):

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .\PranchaQuadros.exe --autoteste; type $env:LOCALAPPDATA\PranchaQuadros\autoteste.txt
```

O autoteste gera um vídeo sintético localmente e executa o fluxo completo (extração, prancha, exportação,
preservação do original, arquivo inválido, registro técnico e reprodutor).

---

## 2. Para desenvolvedores (código-fonte)

### Requisitos

- Windows 10/11 64 bits
- Python **3.14** 64 bits (testado com 3.14; versões 3.11+ devem funcionar)

Não é preciso instalar o FFmpeg: as bibliotecas FFmpeg já vêm dentro das dependências (`av` e `PySide6`).

### Instalação

```powershell
py -V:3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

A internet só é necessária neste passo. Para instalar em uma máquina sem internet, baixe as wheels em outra
máquina e copie a pasta:

```powershell
# máquina com internet
.\.venv\Scripts\python.exe -m pip download -r requirements-dev.txt -d wheels --only-binary=:all:
# máquina sem internet
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements-dev.txt
```

### Executar

```powershell
.\.venv\Scripts\python.exe run_app.py            # ou: python -m prancha
.\.venv\Scripts\python.exe run_app.py video.mp4  # abre já com um vídeo
```

### Testes

```powershell
$env:QT_QPA_PLATFORM="offscreen"; .\.venv\Scripts\python.exe -m pytest -q tests
```

| Critério de aceitação | Onde é verificado |
|---|---|
| 1 — Extração por intervalo (10 s) | `test_extraction.py::test_1_interval_10s` (5 formatos; o conteúdo de cada quadro é conferido), `test_gui.py` |
| 2 — Quantidade (12 quadros) | `test_extraction.py::test_2_count_12_within_range` |
| 3 — Seleção manual com remoção | `test_extraction.py::test_3_manual_random_access`, `test_gui.py::test_full_flow` |
| 4 — Grade de 3 colunas com legendas | `test_plate.py::test_4_three_columns_captions_below` |
| 5 — PNG idêntico à prévia | `test_plate.py::test_5_export_png_identical_to_preview`, `test_gui.py::test_full_flow` |
| 6 — Preservação do original | `test_extraction.py::test_6_original_untouched`, `test_plate.py::test_export_refuses_to_overwrite_original` |
| 7 — Funcionamento offline | `test_gui.py` (fluxo completo com conexões de rede bloqueadas) |
| 8 — Arquivo inválido | `test_extraction.py::test_8_*`, `test_gui.py::test_invalid_file_does_not_crash` |
| 9 — Registro técnico | `test_plate.py::test_9_report_consistent` |

Os vídeos de teste são gerados pelos próprios testes (`prancha/testvideo.py`): cada quadro traz seu número
codificado em blocos preto e branco, o que permite conferir **qual** quadro foi extraído, não só o tempo.
O teste de rotação usa o `ffmpeg` do PATH, se houver (caso contrário é ignorado).

### Gerar o executável

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

O script cria/atualiza o `.venv`, roda os testes, executa o PyInstaller com `PranchaQuadros.spec`, roda o
autoteste **no executável gerado** e cria `dist\PranchaQuadros-1.0.0-win64.zip`. Resultado em
`dist\PranchaQuadros\PranchaQuadros.exe` (pasta autocontida, ~300 MB).

Manualmente: `.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean PranchaQuadros.spec`.

**macOS (futuro):** o código não usa APIs exclusivas do Windows. Em um Mac, crie o venv com Python 3.14,
instale `requirements-dev.txt`, gere `assets/icone.icns` e descomente o bloco `BUNDLE` no fim do `.spec`.
As fontes são procuradas também em `/System/Library/Fonts`.

---

## 3. Arquitetura

```
prancha/
  core/                 (sem dependência de interface — testável isoladamente)
    probe.py            leitura das informações do vídeo (equivalente ao ffprobe), erros em português
    extraction.py       planejamento dos tempos, FrameGrabber (busca + decodificação exata), extração
    layout.py           cálculo da grade, modelos, renderização determinística da prancha (Pillow)
    export.py           gravação atômica PNG/JPEG/PDF e quadros individuais, proteção do original
    report.py           registro técnico TXT/CSV e verificação de preservação
    hashing.py          SHA-256 local
    timefmt.py          formatação HH:MM:SS(.mmm) e leitura de tempos digitados
    fonts.py            fontes TrueType locais
    tempstore.py        pasta temporária da sessão (apagada ao sair)
  gui/
    main_window.py      janela principal, fluxo, tarefas em segundo plano
    player.py           reprodutor (QtMultimedia) + exibição de quadro exato (PyAV) quando pausado
    frames_model.py     lista ordenada de quadros (fonte única de prévia, exportação e registro)
    plate_panel.py      configurações da prancha e visualizador da prévia
    workers.py          threads de tarefas e de renderização (interface nunca congela)
    dialogs.py          diálogos e ajuda
  selftest.py           autoteste do executável (--autoteste)
  testvideo.py          gerador de vídeos sintéticos para testes
tests/                  pytest
```

### Por que PyAV em vez de chamar `ffmpeg.exe`/`ffprobe.exe`

O PyAV é a interface Python das **mesmas bibliotecas do FFmpeg** (libavformat/libavcodec), distribuída já
compilada. Isso dá:

- marcas de tempo (PTS) exatas de cada quadro decodificado, sem interpretar texto de saída de um processo;
- decodificação direta para a memória (sem arquivos intermediários e sem recompressão do vídeo);
- empacotamento simples: não depende de `ffmpeg.exe` instalado na máquina.

O reprodutor usa o QtMultimedia, cujo back-end também é o FFmpeg (DLLs do PySide6). OpenCV não foi
necessário.

### Regra temporal

Para cada instante solicitado usa-se o **quadro em exibição** naquele instante: o último quadro cujo PTS é
menor ou igual ao instante (como um reprodutor pausado). O **tempo efetivo** é o PTS desse quadro em
segundos, medido a partir do início do arquivo. O registro guarda solicitado, efetivo, PTS e base de tempo.
Legendas truncam o tempo (nunca arredondam para cima). Se o quadro em exibição começar antes do início do
trecho escolhido, usa-se o quadro seguinte — nenhum quadro fica fora do trecho. Instantes que caem no mesmo
quadro (intervalo menor que a duração de um quadro) são unificados e informados ao usuário.

Arquivos sem PTS: o tempo é estimado pela contagem de quadros e marcado como “(estimado)” na legenda e no
registro.

### Cor, geometria e redimensionamento

- Conversão YUV→RGB com a matriz informada no arquivo; quando ausente, BT.709 para HD e BT.601 para SD
  (mesmo critério dos reprodutores). A conversão usada fica no registro. Nenhum filtro de cor, nitidez ou
  contraste é aplicado.
- Rotação gravada por celulares e proporção de pixel (vídeo anamórfico) são aplicadas na prancha por padrão
  (opção desativável); o resultado foi conferido contra o próprio FFmpeg.
- Redimensionamento na prancha: LANCZOS, sempre preservando a proporção. Bordas são desenhadas **fora** da
  área do quadro; a legenda fica fora da imagem (exceto se o usuário escolher “sobreposta”).

---

## 4. Limitações conhecidas

- Pranchas acima de 400 megapixels são recusadas (limite de memória); acima de 80 megapixels há aviso.
  O JPEG não aceita dimensões acima de 65.500 px. A resolução escolhida nunca é reduzida automaticamente.
- Arquivos `.dav` proprietários de alguns DVRs só abrem se o FFmpeg reconhecer o formato.
- Quando o QtMultimedia não consegue reproduzir um arquivo que o FFmpeg decodifica, o reprodutor passa ao
  modo quadro a quadro (a extração não é afetada).
- Datas de criação/modificação vêm do sistema de arquivos e podem refletir a cópia, não a gravação.

Licenças de terceiros: [LICENSES.md](LICENSES.md).
