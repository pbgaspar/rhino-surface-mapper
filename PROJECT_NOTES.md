# Rhino Surface Mapper — funcionamento atual

Revisto em 11/09/2026 com base no código do espaço de trabalho.

## Arranque e dependências

Na pasta `rhino-surface-mapper`:

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 rhino_surface_mapper.py
```

A instalação de dependências só é necessária na preparação do ambiente. O comando `py -3.13 rhino_surface_mapper_qt.py` também funciona. A aplicação principal usa apenas PyQt6, num único ciclo de eventos, incluindo o overlay.

O recurso gráfico ativo é `assets/Rhino.svg`, rodado pelo rumo exato da telemetria. A altura inicial do desenho é 56 píxeis lógicos, independente do zoom. Incluir a pasta `assets/` ao distribuir o programa. Os 72 PNGs já não são recursos da aplicação principal.

## Telemetria e mapa

Por defeito, a posição é lida de `%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\Status.json`. Em Configurações → Parâmetros ED, Escolher Status.json permite outro caminho.

O temporizador consulta o ficheiro a cada **50 ms**. Uma leitura válida não expira apenas por o ficheiro permanecer inalterado. Falhas de leitura são repetidas; a deteção do radar fica desativada até recuperar dados válidos. Abrir um mapa força nova leitura para apresentar o Rhino sem esperar por movimento. O redesenho evita atualizações quando a telemetria visual não mudou.

O mapa converte latitude/longitude para um referencial local em metros. Regista pontos separados por pelo menos 10 m e assinala saltos superiores a 100 m como interrupções do rasto. O rasto liga pontos também fora da busca, respeitando essas interrupções.

A roda amplia em torno do cursor; o botão direito permite deslocar o mapa e um clique direito num marcador abre o respetivo menu. Botão do meio/Home centra no Rhino; Centrar acompanha a posição. O texto adapta-se ao monitor, com validação em 1080p e 4K. Os números dos destinos têm círculos brancos e contornos de estado.

O combustível tem indicador próprio: `FUEL : 72% ✓ Normal`, `FUEL : 30% ⚠ Baixo`, `FUEL : 15% 🔴 Crítico` ou `FUEL : 0% ⛔ Sem combustível`, consoante o valor.

## Busca e overlay

A busca circular utiliza raio de 3500 m, espaçamento pretendido de 1800 m e **AZ Busca** inteiro entre 000 e 359. O azimute define a orientação inicial; o valor por defeito é norte. Os destinos avançam no sentido horário e podem ser saltados. O mapa guarda o Datum, o índice, o azimute e o histórico.

As cores do rumo dependem do desvio absoluto: até 2º verde sem setas; acima de 2º até 8º amarelo com três setas; acima de 8º vermelho com cinco setas. Sem destino ou dados válidos, cinzento. Estes intervalos não dependem da tolerância configurada da assistência.

O overlay começa escondido. Iniciar busca ou navegação ativa a apresentação automática, visível quando o comandante está no Rhino, mesmo que o jogo perca foco. Sair do veículo oculta-o temporariamente; mudar de janela mantém-no visível; regressar repõe a escolha anterior, incluindo uma ocultação manual pelo botão Overlay. Mostrar automaticamente não rouba o foco ao jogo. Terminar o modo de navegação esconde-o. O botão Iniciar busca passa a Terminar busca, que pede confirmação. Concluir os destinos não equivale por si só a sair do modo.

A deteção automática do menu Esc foi dispensada pelo utilizador em 11/09/2026. Quando necessário, usa o botão Overlay para mostrar/esconder manualmente. O código observa Status.json e o foco; não deteta esse menu. O confinamento do overlay ao monitor do jogo continua pendente.

O overlay é transparente, movível pelo interior, redimensionável pelas bordas/cantos e mantém proporção 2,40. Sair ou fechar a janela principal fecha também o overlay.

## Depósitos, rigs e marcas

- Depósitos: colocados na posição do Rhino, com nome, tamanho e número de rigs. A aplicação impede duplicados a menos de 80 m. O menu permite editar, copiar coordenadas e apagar.
- Rigs: colocados por clique; Escape cancela a colocação. Podem ser apagados pelo menu.
- Marcas: têm diálogo próprio com nome, distância e azimute e opções Alterar/Apagar. Alterar apenas o nome conserva as coordenadas originais, incluindo marcas antigas com distância fracionária ou superior ao limite atual do campo.

Navegar/Parar navegação estão disponíveis nos menus das marcas, depósitos, rigs e pontos de busca. O mapa mostra uma linha ciano e o overlay identifica o destino. Navegar durante uma busca guarda o ponto de pausa; chegar a menos de 100 m do destino inicia o regresso a esse ponto. O botão Busca em pausa permite retomar diretamente a busca.

Os campos numéricos incluem as unidades e usam formatos compactos. Os ângulos são inteiros de 000 a 359. A distância da Marca admite até 99999 m; Cobertura admite 100–5000 m e Scanner 500–5000 m. O formato de quilómetros está preparado no código, mas ainda não há um campo em km na interface.

## Interface e configurações

A proposta 3 foi escolhida, implementada e validada pelo utilizador após as correções de setas e cores.

- Primeira barra: **Mapas** (Novo, Guardar, Abrir), Marca, Depósito, Rig, **Configurações**, Sair.
- Segunda barra: Iniciar/Terminar busca, Saltar próximo/Busca em pausa e Overlay à esquerda; Ass. Direção [F8], Centrar e Fuel à direita.
- Botões com dimensões fixas ao redimensionar a janela. O espaço disponível é aproveitado pelo mapa. Janela mínima: 1150 × 560 unidades lógicas.
- Mapa: sistema e planeta no canto superior esquerdo; Norte no superior direito; Grelha no inferior esquerdo; informação do cursor no inferior direito.
- Painel lateral recolhível, com oito secções inicialmente fechadas: Busca e navegação, Radar, Rhino, Assistência de direção, Parâmetros ED, Mapa, Overlay e Layout. Fechá-lo devolve a largura ao mapa.
- No fim do painel: **Guardar, Carregar e Repor**, em linha. Guardar exporta um ficheiro JSON; Carregar valida o conteúdo antes de aplicar; Repor restaura os valores padrão de todas as secções. Cada secção também permite repor os seus valores.

As alterações são aplicadas imediatamente e persistidas em `options.json`. O ficheiro exportado tem `rhino_settings_version: 1` e um objeto `settings`; é distinto do JSON de um mapa. Carregar atualiza os controlos e as preferências locais. Cancelar os seletores não altera o estado. Um ficheiro de configurações inválido é rejeitado antes da aplicação dos valores.

| Secção | Configurações implementadas |
| --- | --- |
| Busca e navegação | Cobertura 100–5000 m; AZ Busca 000–359º |
| Radar | Alcance 500–5000 m; velocidade da onda 100–3000 m/s, padrão 667; cor da onda e da área varrida |
| Rhino | Tamanho 20–160 px, padrão 56; cor da blindagem, preservando os restantes materiais do SVG |
| Assistência de direção | Velocidade máxima estimada 15–40 m/s, padrão 15; duração base máxima 200–1000 ms, padrão 800; tolerância 0–180º, padrão 3 |
| Parâmetros ED | Fire group A–Z, padrão A; perfil .binds automático ou escolhido; seleção de Status.json |
| Mapa | Cores de fundo, grelha, rasto e cobertura; escala do texto 75–175% |
| Overlay | Largura 240–900 px, padrão 360; opacidade 25–100% |
| Layout | Como o Windows / Dark / Light; família de letra; tamanho 8–11 pt; painel 280–440 px; altura dos botões 28–44 px |

No tema Dark, o fundo inicial é cinzento médio `#606060`, com grelha `#747474`. As cores personalizadas prevalecem sobre o tema. O contorno da onda e a área varrida usam a mesma cor configurada; já não existe preenchimento quase branco fixo. Todos os campos numéricos do painel usam o estilo Fusion com setas verticais, incluindo Cobertura, AZ Busca e Alcance do scanner.

A exportação inclui as configurações registadas no painel, mas não a geometria/posição das janelas, o estado de Centrar nem o caminho de Status.json. Os parâmetros contidos num mapa aberto continuam a prevalecer sobre os valores de busca em uso.

## Assistência de direção — funcionamento atual

F8 ou Ass. Direção [F8] ativa o seguimento de um destino de busca ou Navegar. O modo temporário de ensaio está desativado (`direction_test = False`). A velocidade é estimada a partir do deslocamento e do tempo; não é lida do velocímetro.

A duração base usa a referência provisória de 46,5º/s, com fator 0,7 e redução acima de 10 m/s. Os multiplicadores por desvio são 1× até 30º, 1,5× até 90º, 2× até 120º e 3× acima de 120º. Após cada correção exige telemetria posterior ao comando. A tolerância padrão de 3º é configurável e independente das cores do overlay.

F8, intervenção manual ou fim da navegação/busca desligam a assistência. Perda de foco, telemetria inválida, saída do Rhino, painel/torre ou falha de leitura do joystick libertam as teclas e colocam-na em espera; retoma com condições válidas e dados novos. Não há expiração da espera de foco aos 10 s. Esc não desliga a assistência; continua a cancelar a colocação de rigs. Fechar a aplicação liberta os comandos.

Na chegada a um destino de Navegar (menos de 100 m), com assistência ativa, envia S uma vez durante 3 s. F8 ou perda das condições interrompem a travagem. Não há confirmação de velocidade zero, deteção de obstáculos ou controlo automático geral do acelerador. Pontos intermédios da busca e paragem manual da navegação não desencadeiam esta travagem.

O utilizador confirmou no jogo os escalões de curva e a paragem na chegada. A calibração entre velocidades e condições diferentes continua a beneficiar de testes reais; os testes automáticos não medem a dinâmica do veículo.

## Radar, coberturas e ficheiros

O radar observa passivamente o disparo primário SRV definido no perfil .binds; exige foco no jogo, Analysis Mode, fire group configurado e telemetria válida. A seleção automática do perfil usa StartPreset.4.start. Ao mudar de contexto é necessário libertar o disparo antes de voltar a premir. Uma onda de cada vez, sem fila; manter premido repete ao terminar. A velocidade inicial de 667 m/s dá aproximadamente 3 s para 2 km. A observação do botão não confirma o sucesso de um disparo no jogo.

A cobertura de radar usa centros e raios em `radar_coverage`; guardar durante um pulso conserva apenas a parte varrida. Abrir não reinicia animações. A cobertura do percurso é reconstruída dos pontos, respeitando interrupções; a largura atual aplica-se a todo o percurso, sem larguras históricas por ponto.

Guardar/Abrir em Mapas usa JSON com parâmetros, pontos, marcas, depósitos, rigs, busca e radar. Posição atual e combustível vêm da telemetria. `MAPAS/` contém mapas do utilizador. `assets/` deve acompanhar a distribuição, incluindo Rhino.svg, Rhino_App.svg e spin-up.svg/spin-down.svg.

## Validação e pendentes

Última execução: **94 testes passaram**, incluindo entradas numéricas, pintura, navegação, assistência e ficheiros de configurações. O utilizador confirmou o layout, as correções de setas/cores e anteriormente o movimento do overlay, coberturas, direção e chegada. Guardar/Carregar/Repor tem validação automática; falta confirmação manual específica.

A partir da pasta do programa:

```powershell
py -3.13 -m unittest discover -s tests -v
```

Os testes Qt usam renderização fora do ecrã e não cobrem todas as escalas Windows, monitores ou condições do jogo. Pendentes: confinamento do overlay ao monitor, validação visual entre monitores, condições transitórias da assistência e comentários didáticos. Ver [TODO.md](TODO.md).

## Histórico resumido

A aplicação atual usa um único ciclo Qt. A versão antiga permanece arquivada como cópia de segurança; os ZIPs de referência são imutáveis. Maquetes em `../outputs/propostas-interface/` documentam a escolha da proposta 3. Os ensaios de direção de 5 s e depois de 2 s foram etapas de calibração, não o modo atual. O módulo turn_trial.py permanece no código, mas `direction_test` inicia desativado.
