# Guia de leitura — aprender Python com o Rhino Surface Mapper

Revisto em 11/09/2026 a partir dos módulos atuais.

## Que versão estamos a estudar?

A aplicação arranca com `py -3.13 rhino_surface_mapper.py`. A sua interface é inteiramente PyQt6. Os módulos ativos são:

| Ficheiro | Responsabilidade |
| --- | --- |
| rhino_surface_mapper.py | Entrada principal, que chama main() |
| rhino_surface_mapper_qt.py | Janela, mapa, SVG, eventos, opções e atualização periódica |
| layout_options.py | Barras, painel, temas, registo e ficheiros de configurações |
| mapper_core.py | Estado, coordenadas, telemetria, busca, marcas e dados guardados |
| qt_map_operations.py | Diálogos, ficheiros, depósitos, rigs, marcas e menus |
| pyqt_overlay.py | Janela transparente e interação do overlay |
| radar.py | Estado e progressão temporal dos pulsos |
| radar_input.py | Leitura passiva dos controlos e perfis do jogo no Windows |
| steering.py | Decisões de direção, velocidade estimada e limites de correção |
| steering_input.py | Leitura de intervenção manual e toques de teclado limitados no Windows |
| steering_ui.py | Botão/F8, condições de ativação e mensagens da assistência |
| numeric_fields.py | Campos numéricos compactos, unidades e formato português |

O desenho ativo é `assets/Rhino.svg`. `QSvgRenderer` carrega o vetor e o pintor roda-o conforme o rumo. Não há escolha de imagens em passos de 5° na versão atual.

A versão antiga está arquivada como cópia de segurança, com os seus próprios módulos e imagens; a localização consta do histórico de migração. Os PNGs retirados da raiz estão em `archive/obsolete-images-2026-09-10/`. Estas pastas e `backups/` não fazem parte do código ativo. Os ZIPs são referências imutáveis.

## Ordem recomendada de leitura

1. Começa por `MapperState.__init__`: é o inventário dos dados do programa.
2. Lê `process_status`, `llxy` e `xyll`: explicam como os dados do jogo se tornam posições em metros.
3. Lê `start_search`, `update_next` e `overlay_navigation`: explicam a navegação.
4. Lê `rhino_surface_mapper.py`, depois `main`, `MapperWindow.__init__`, `poll` e `refresh` no módulo da janela.
5. Lê `MapView.screen`, `world`, `zoom_at` e `paintEvent` para compreender o desenho.
6. Passa para os diálogos em `qt_map_operations.py` e para o movimento do overlay.
7. Lê `RadarPulse.tick`, `MapperWindow.update_radar` e depois `radar_input.py`: separa primeiro a animação da leitura dos dispositivos. `numeric_fields.py` explica a apresentação das unidades.

## Conceitos de Python usados aqui

- Uma **classe** descreve dados e operações relacionados. Uma **instância** é um objeto concreto criado a partir dela: `self.state = MapperState()`.
- `self` é a instância sobre a qual um método está a trabalhar. `self.points` é a lista de pontos dessa instância.
- `None` indica ausência de valor conhecido. É diferente de zero: latitude 0 é uma coordenada válida.
- Uma **lista**, como `points`, guarda vários elementos ordenados. Um **dicionário**, como cada ponto, associa nomes a valores: `point['x']`.
- Uma **tupla** agrupa resultados, por exemplo `(x, y)`. A instrução `x, y = ...` distribui esses resultados por duas variáveis.
- `return` devolve um resultado e termina a função. Um `return` sem expressão termina sem devolver dados úteis.
- `if`, `elif` e `else` selecionam alternativas. A indentação define quais as instruções que pertencem a cada bloco.
- `for` percorre uma coleção. Uma compreensão, como `[p['x'] for p in points]`, cria uma lista com um valor retirado de cada ponto.
- `lambda` cria uma função curta. Nas ligações dos controlos, `field=field` guarda o nome do atributo no momento da criação.
- `try` e `except` tratam falhas previstas, como um ficheiro que ainda está a ser escrito pelo jogo.
- Uma cadeia `f'...'` permite inserir valores e formatá-los: `{fuel:.0f}` mostra um número sem casas decimais.
- As indicações `float`, `bool`, `Path` e `->` nas assinaturas documentam os tipos esperados. Não substituem a validação dos dados recebidos.
- `@property` permite ler um resultado calculado como atributo. `@staticmethod` identifica um método que não precisa de `self`.
- Textos entre três aspas no início de módulos/classes/funções são **docstrings**. Podem ser consultados com `help()`. Linhas começadas por `#` explicam o código ao leitor.

Os nomes de métodos Qt, como `paintEvent` e `mouseMoveEvent`, permanecem em inglês porque fazem parte da API. Os comentários explicam a sua função em português de Portugal.

## Como tudo funciona em conjunto

`QApplication.exec()` aguarda eventos: cliques, teclas, pedidos de desenho e temporizadores. Não é necessário escrever um ciclo infinito próprio.

A cada 50 ms, `QTimer` chama `poll`. Quando a data do ficheiro mudou, `poll` lê JSON e entrega o dicionário a `MapperState.process_status`. O núcleo atualiza o Rhino e os pontos. `refresh` atualiza os textos e pode pedir um novo desenho com `update()`; `map_signature` ajuda a evitar desenhos quando os dados visuais não mudaram. O Qt chama posteriormente `paintEvent`; pedir um desenho não significa desenhar imediatamente.

Um segundo temporizador, a 16 ms, chama `update_radar` para observar os controlos e avançar a animação. Um disparo observado inicia o pulso; não é uma confirmação de sucesso pelo jogo. `RadarPulse.tick` conserva a área coberta em `radar_coverage`. Não usa pausas que bloqueiem a interface.

Um sinal Qt liga uma origem a um destino. `button.clicked.connect(self.save_map)` significa: quando este botão emitir clicked, chamar save_map. O mapa também emite os seus próprios sinais, para não precisar de conhecer os diálogos.

Os diálogos modais impedem a interação normal com a janela principal, mas os temporizadores Qt podem continuar. Por isso, depois de editar um depósito, o código verifica se ainda pertence ao mesmo mapa/corpo.

## Unidades e orientação

- Latitude, longitude e rumo: graus.
- Posições X/Y, cobertura, scanner e distâncias: metros.
- Ecrã e dimensões da janela: píxeis.
- `scale`: píxeis por metro.
- No mapa X cresce para este e Y para norte. No ecrã Y cresce para baixo; as conversões invertem esse sinal.
- A projeção é uma aproximação local, não um mapa global do planeta. A leitura de mapas rejeita centros exatamente nos polos, onde o cálculo da longitude é singular.

## Estado do mapa e posição atual são coisas diferentes

O JSON guardado conserva pontos, depósitos, rigs, marcas, cobertura dos pulsos, centro, parâmetros e estado da busca, incluindo o azimute inicial. A posição atual do Rhino e o combustível vêm de Status.json. Ao abrir um mapa, a aplicação força uma leitura imediata de Status.json para não esperar que o jogo altere a data do ficheiro.

A leitura de um mapa cria primeiro um candidato, valida-o e só depois o instala. Assim, um erro não deixa metade dos dados novos misturados com metade dos antigos.

## Regra do overlay

Ao arrancar, está escondido. Busca, navegação para um objeto e regresso ao ponto de pausa são modos autorizados. `overlay_allowed` exige também presença no Rhino; `refresh` aplica a escolha manual de visibilidade, independentemente do foco. `overlay_navigation_active` regista se existe um modo de navegação e `overlay_mode_active` conserva a escolha de mostrar/esconder. Separar estas condições permite ocultar temporariamente ao sair do veículo, sem apagar a escolha manual. A entrada num novo modo ativa a apresentação automática. `WA_ShowWithoutActivating` evita roubar foco ao mostrar a janela. O botão dinâmico Terminar busca permite terminar o modo.

## Como estudar as configurações

`MapperWindow` combina `LayoutOptions`, `SteeringUI`, `MapOperations` e `QMainWindow`. A construção inicial liga os controlos; `build_layout_options` organiza as barras e o painel. Os widgets existentes são reutilizados para conservar os sinais.

Em `layout_options.py`, `section` cria o cabeçalho e conteúdo recolhíveis; `number` e `color` ligam entradas ao estado e à persistência. `setting_fields` associa cada chave a três funções: ler, aplicar e validar. `export_settings` recolhe os valores atuais; `import_settings` valida todo o ficheiro antes de aplicar. `loading_settings` evita escritas intermédias durante importação/reposição. `reset_settings` repõe primeiro Layout, para calcular depois as cores padrão do tema correto.

`apply_theme` trata dos estilos e cores iniciais. As escolhas guardadas prevalecem sobre o tema. `MapView.draw_corners` apresenta sistema/planeta, Norte, grelha e cursor. Os campos numéricos do painel usam Fusion para evitar diferenças das setas nativas Windows; os SVGs spin-up.svg e spin-down.svg fazem parte dos recursos da aplicação.

## Onde alterar

- Barras, secções, temas e persistência: `layout_options.py`.
- Desenho, cores, escala, cantos do mapa: `MapView` em `rhino_surface_mapper_qt.py`.
- Parâmetros e validação de mapas: `mapper_core.py`; operações e diálogos: `qt_map_operations.py`.
- Onda e repetição: `radar.py`; leitura dos comandos do jogo: `radar_input.py`.
- Decisões de direção: `steering.py`; emissão e libertação das teclas: `steering_input.py`; ligação à interface: `steering_ui.py`.
- Aspeto/interação do overlay: `pyqt_overlay.py`.

Alterar um intervalo de valores pode exigir atualizar controlo, validação e testes. O JSON de configurações versionado é distinto do JSON do mapa. Não eliminar nem alterar os ZIPs de referência.

## Assistência de direção — funcionamento atual

F8 ou Ass. Direção [F8] ativa o seguimento de um destino de busca ou Navegar. O modo temporário de ensaio está desativado (`direction_test = False`). A velocidade é estimada a partir do deslocamento e do tempo; não é lida do velocímetro.

A duração base usa a referência provisória de 46,5º/s, com fator 0,7 e redução acima de 10 m/s. Os multiplicadores por desvio são 1× até 30º, 1,5× até 90º, 2× até 120º e 3× acima de 120º. Após cada correção exige telemetria posterior ao comando. A tolerância padrão de 3º é configurável e independente das cores do overlay.

F8, intervenção manual ou fim da navegação/busca desligam a assistência. Perda de foco, telemetria inválida, saída do Rhino, painel/torre ou falha de leitura do joystick libertam as teclas e colocam-na em espera; retoma com condições válidas e dados novos. Não há expiração da espera de foco aos 10 s. Esc não desliga a assistência; continua a cancelar a colocação de rigs. Fechar a aplicação liberta os comandos.

Na chegada a um destino de Navegar (menos de 100 m), com assistência ativa, envia S uma vez durante 3 s. F8 ou perda das condições interrompem a travagem. Não há confirmação de velocidade zero, deteção de obstáculos ou controlo automático geral do acelerador. Pontos intermédios da busca e paragem manual da navegação não desencadeiam esta travagem.

O utilizador confirmou no jogo os escalões de curva e a paragem na chegada. A calibração entre velocidades e condições diferentes continua a beneficiar de testes reais; os testes automáticos não medem a dinâmica do veículo.

## Validação

A última suite passou **94 testes**. `test_layout_options.py` cobre dimensões fixas, expansão do mapa, cliques nas setas, cores pintadas e exportação/importação/reposição; `test_steering.py` separa decisões, interface e emissão simulada. O teste de cor do percurso fixa explicitamente a paleta para não depender das preferências pessoais.

A aprovação visual do utilizador cobre o ambiente que utilizou. Renderização Qt fora do ecrã não garante comportamento em todos os monitores. Consultar [TODO.md](TODO.md) para pendências e [PROJECT_NOTES.md](PROJECT_NOTES.md) para valores e utilização. Os ensaios antigos permanecem apenas como código de apoio em turn_trial.py; não estão ativos por defeito.
