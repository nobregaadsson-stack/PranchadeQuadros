# Componentes de terceiros

| Componente | Versão | Uso | Licença |
|---|---|---|---|
| Python | 3.14 | linguagem / runtime embutido no executável | PSF License |
| PySide6 / Qt 6 (Essentials + Addons) | 6.12.0 | interface gráfica e reprodutor (QtMultimedia) | LGPLv3 |
| FFmpeg embutido no PySide6 (`avcodec-63.dll` etc.) | a da wheel (libavcodec 63) | back-end do reprodutor | LGPL v2.1+ |
| PyAV (`av`) | 19.0.1 | leitura e decodificação de vídeo | BSD-3-Clause |
| FFmpeg embutido no PyAV (`av.libs`) | a da wheel (libavcodec 63) | bibliotecas de leitura/decodificação | **GPL v2+** (a compilação do PyAV inclui libx264 e libx265) |
| Pillow | 12.3.0 | composição e exportação de imagens/PDF | MIT-CMU (HPND) |
| PyInstaller (somente na compilação) | 6.22.3 | geração do executável | GPLv2 com exceção para o bootloader |

## Observações para distribuição

- **Uso interno** (na própria instituição) não gera obrigações adicionais.
- **Redistribuição a terceiros** do executável: por incluir FFmpeg compilado com componentes GPL (via PyAV),
  o pacote deve ser acompanhado dos textos de licença e da oferta do código-fonte correspondente (este
  projeto e os componentes indicados). Os textos de licença estão nas pastas `*.dist-info` copiadas pelo
  PyInstaller para `_internal`.
- Se for necessário um pacote somente LGPL, é possível compilar o PyAV contra um FFmpeg LGPL (sem x264/x265);
  o aplicativo só usa decodificação, portanto não depende desses codificadores (eles só são usados pelos
  testes para gerar vídeos sintéticos).
- O Qt é ligado dinamicamente (DLLs separadas na pasta do aplicativo), como exige a LGPL.
