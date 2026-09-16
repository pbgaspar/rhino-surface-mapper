# Lista de tarefas

Revista em 13/09/2026 com base no código e na conversa «Testar e corrigir Surface Mapper», incluindo as últimas confirmações do utilizador. O projeto ativo usa PyQt6. Os ZIPs de referência e a versão antiga arquivada como cópia de segurança permanecem intactos. Implementado não significa validado manualmente em todas as condições.

## Por fazer — Ver e manter

- [ ] **Aperfeiçoar o visual**, sobretudo a ficha de informações e os cartões de planetas, com cores coerentes com a aplicação. A primeira melhoria foi apresentada; o utilizador considerou «um pouquinho melhor» e adiou o restante.
- [ ] **Tornar configurável o mínimo de caracteres da pesquisa de sistemas.** Atualmente está fixo em 2 no código; a configuração foi pedida mas ainda não existe.
- [ ] **Completar a fase de manutenção:** apagar versão, renomear, duplicar e exportar. Abrir como mapa atual, favoritos e proteção já estão implementados. As operações futuras devem respeitar a proteção do ficheiro.

## Por testar — Ver e manter

- [ ] Confirmar no jogo a deteção imediata do Rhino nos dois modos após a correção da abertura com StarSystem vazio, incluindo Rhino parado.
- [ ] Validar a caixa quadrada na indentação (depósitos em cima, favorito/protegido em baixo) e as caixas navy de depósitos em duas linhas, no mapa principal e na pré-visualização.
- [ ] Confirmar no ambiente do utilizador os indicadores X/número de depósitos, mineração, estrela dourada e chave; verificar as caixas Favorito/Proteger e os símbolos no rodapé.
- [ ] Testar no jogo um mapa protegido: Continuar exploração cria uma nova versão editável; Só minerar permite navegar entre depósitos, marcas e rigs sem radar, rasto, cobertura, busca ou novos registos. Confirmar fecho sem gravação e original intacto.
- [ ] Confirmar minimizar, maximizar, restaurar, redimensionar e fechar/reabrir, mantendo o mapa principal e a navegação intactos.
- [ ] Validar pesquisa com menos de dois caracteres, resultados filtrados, ausência de resultados e sistemas com nomes compridos; confirmar que só um planeta fica expandido.
- [ ] Confirmar a separação de planeta `2` e `2 a` com os mapas antigos corrigidos e a ordem das versões. Atualmente a lista ordena pela data de modificação do ficheiro; verificar a coerência com a última gravação apresentada, incluindo após migração de datas.
- [ ] Comparar pré-visualização e ficha com mapas reais: percurso e quebras, nomes, depósitos/tamanhos/rigs/coordenadas, marcas e rigs; incluir mapas vazios e com muitos registos.
- [ ] Conferir `Busca efetuada` e saltos nos casos sem busca, busca parcial e busca concluída, com e sem destinos saltados.
- [ ] Validar a migração de datas num mapa antigo: preencher apenas datas em falta, conservar a última gravação original e manter os dados ao reabrir. A consulta pode gravar estas datas no JSON, conforme autorizado; não é estritamente só leitura do ficheiro.
- [ ] Verificar o comportamento com ficheiros inválidos ou inacessíveis e ao mudar de sistema/mapa, sem apresentar informação anterior como se pertencesse à nova seleção.
- [ ] Validar legibilidade nos temas Windows/Dark/Light, em 1080p/4K e diferentes escalas Windows, sobretudo listas longas e a ficha de informações.

## Por fazer — restante projeto

- [ ] **Nomes de marcas e depósitos com sugestões de commodities.** Substituir o campo Nome por uma caixa editável com lista suspensa e filtragem durante a escrita. Incluir a lista validada das 21 commodities; permitir selecionar uma sugestão ou escrever qualquer outro nome livremente.
- [ ] **Limite configurável para o nome no overlay.** Mostrar por defeito os primeiros 16 caracteres, incluindo espaços, mantendo as dimensões e a proporção atuais da caixa. Cortar diretamente à direita, sem reticências: `Classified Experimental Equipment` deve aparecer como `Classified Expe`. Acrescentar a configuração para aumentar ou diminuir esse limite, sem alterar automaticamente o tamanho da caixa.
- [ ] **Avaliar a distribuição do executável depois da otimização do mapa.** Comparar o atual executável único com uma distribuição portátil em pasta. O objetivo é melhorar o arranque e o diagnóstico; não apresentar esta alteração como solução para o desempenho durante a exploração.
- [ ] Confinar o overlay aos limites do monitor do jogo durante movimento e redimensionamento.
- [ ] Afinar a assistência se os testes em velocidades/terrenos diferentes indicarem necessidade. Escalões e travagem na chegada já foram confirmados pelo utilizador.
- [ ] Completar comentários didáticos em português de Portugal nos módulos novos e funções acrescentadas.

## Por testar — restante projeto

- [ ] **Completar a validação da gestão automática por PML no jogo.** Usar a referência atual de 13 km; testar nenhum/um/vários PML próximos, reutilização de PML existente, numeração `JD<n>` por planeta e cancelamentos. A transição corrigida para outro PML, sem conservar o centro/ficheiro anterior, recebeu confirmação «Está ok».
- [ ] **Completar a validação de Novo/Abrir/Guardar/Sair.** Novo cria uma versão limpa gravada do PML; confirmar todas as opções do diálogo do mapa atual — Não gravar, Nova Versão, Gravar e Cancelar — incluindo mapa vazio, fecho pelo X e botão Sair. A criação de cinco versões distintas já foi confirmada pelo utilizador; não está pendente repetir essa confirmação básica.
- [ ] **Validar a identificação do sistema no jogo.** Quando `StarSystem` vem vazio no `Status.json`, o programa conserva o último valor válido se o planeta se mantiver igual; sem um mapa/sistema já conhecido não cria PML novo nem inventa dados.
- [ ] Validar a revisão visual em 1080p/4K, diferentes escalas Windows e mudança de monitor. O utilizador aprovou o aspeto no seu ambiente; isso não equivale a testar todas as combinações.
- [ ] Confirmar no jogo a espera/retoma da assistência em todas as condições transitórias e a ausência de desligamentos inesperados.
- [ ] Confirmar manualmente a troca de ficheiros pelo novo Guardar/Carregar/Repor de Configurações. Exportação, importação, reposição e rejeição de valores inválidos têm testes automáticos.

## Implementado — Ver e manter

- [x] Menu Mapas com Abrir, Guardar, Novo e Ver e manter; corrigida também a reconstrução do menu pelo layout.
- [x] Janela independente não modal, com controlos de minimizar/maximizar e redimensionamento.
- [x] Pesquisa nas subpastas de sistemas em MAPAS, filtrada a partir de dois caracteres.
- [x] Planetas com nome abreviado em cartões expansíveis; apenas um aberto de cada vez; versões listadas por data de modificação decrescente.
- [x] Migração da identidade pelo nome normalizado do ficheiro para distinguir planeta 2 de 2 a.
- [x] Pré-visualização independente do mapa ativo, com percurso e nomes de depósitos, marcas e rigs.
- [x] Ficha com datas, PML, pontos do percurso, depósitos, marcas, rigs, coordenadas e resumo de busca/saltos.
- [x] Remover a faixa superior excessiva e aplicar uma primeira melhoria visual à lista e à ficha.
- [x] Definir ícones SVG explícitos para as setas de expandir/recolher, que o estilo dos cartões tinha ocultado.
- [x] Utilizador confirmou «Setas ok».
- [x] Indicadores antes do nome do mapa: X sem depósitos, número e símbolo de mineração quando existem, estrela dourada de favorito e chave dourada com dentes para proteção.
- [x] Caixas Favorito e Proteger na ficha; atributos persistidos no JSON e sincronizados com o mapa principal. Alterar estes atributos preserva os dados e a data de modificação do ficheiro.
- [x] Abrir mapa pela biblioteca e escolher Continuar exploração ou Só minerar quando protegido, também na abertura normal e automática por PML. Continuar exploração conserva o original e cria uma versão editável.
- [x] Modo Só minerar com Rhino, pontos marcados, informação e navegação, sem desenho/registo de radar, percurso, coberturas ou busca. Edição e gravação bloqueadas; sair não pede gravação.
- [x] Proteção verificada também no ficheiro de destino ao guardar; os mapas protegidos não são regravados pela migração automática de datas.
- [x] Estrela e chave no rodapé antes do nome, com indicação Só minerar quando aplicável.
- [x] Substituir a coluna adicional de indicadores pelo desenho na indentação existente, numa caixa quadrada com duas linhas, conservando a altura dos cartões.
- [x] Depósitos representados por caixas navy com texto branco: símbolo e nome na primeira linha, tamanho e rigs na segunda, partilhadas pela pré-visualização e pelos modos de exploração/mineração. Toda a caixa permite selecionar o depósito.
- [x] Reler a telemetria imediatamente ao instalar um mapa e aceitar StarSystem vazio quando o planeta coincide; não aceitar a posição de outro planeta.
- [x] Gravar created_at e last_saved_at no JSON; preencher datas em falta nos mapas antigos pelas propriedades do ficheiro, conservando a última gravação original.

## Implementado e confirmações — gestão de mapas

- [x] Organização MAPAS/<Sistema>/<Planeta> [<PML>].json e versões v2, v3, etc.; utilizador confirmou cinco versões distintas.
- [x] Novo preserva o contexto do PML e cria imediatamente uma versão limpa gravada.
- [x] Decisão de outro PML além de 13 km; corrigida a transição para limpar centro e ficheiro anteriores e gravar o mapa inicial do novo PML. Utilizador confirmou «Está ok».
- [x] Diálogo para decidir o destino do mapa atual; rótulo Não gravar em vez de Apagar e seleção das listas com maior contraste.
- [x] Rodapé numa única linha, nome do ficheiro seguido de data/hora à esquerda e navegação à direita; barra de estado redundante ocultada.

## Concluído — interface e configurações

- [x] Escolher a proposta 3 e implementar duas barras com painel recolhível.
- [x] Manter tamanho dos botões ao redimensionar a janela.
- [x] Organizar comandos e informação nos quatro cantos do mapa conforme pedido.
- [x] Organizar configurações em oito secções recolhíveis, inicialmente fechadas.
- [x] Personalizar tamanho/cor do Rhino, mapa, radar, texto e apresentação do overlay.
- [x] Implementar temas Windows/Dark/Light e persistência das preferências.
- [x] Corrigir setas nos campos derivados e uniformizar o estilo. Utilizador confirmou «Tudo ok».
- [x] Aplicar a cor da onda à área varrida e respeitar cores personalizadas em Dark. Utilizador confirmou as correções.
- [x] Renomear Opções para Configurações e acrescentar Guardar, Carregar e Repor em linha.

## Concluído — mapa, radar e navegação

- [x] SVG aprovado com rotação pelo rumo exato; recursos antigos arquivados.
- [x] Leitura de Status.json a 50 ms; radar/animação a 16 ms; repetição de leituras falhadas.
- [x] Radar por disparo primário SRV, condicionado por foco, Analysis Mode e fire group. Cliques curtos, rato e T16000M validados pelo utilizador.
- [x] Uma onda de cada vez, repetida quando o disparo permanece premido; cobertura dos pulsos guardada com o mapa, sem reiniciar animações ao abrir.
- [x] Cobertura contínua do percurso e restauração ao guardar/abrir, confirmadas pelo utilizador.
- [x] Otimizar o desenho de mapas longos com caminhos vetoriais Qt reutilizáveis, preservando todos os pontos e as quebras reais do percurso. O utilizador confirmou que o mapa permanece utilizável; a diferença perceptível foi pequena no mapa de referência.
- [x] Renomear marcas sem deslocar coordenadas; validação de mapas antes de substituir o estado.
- [x] Navegar em marcas, depósitos, rigs e pontos de busca; pausa da busca, retorno ao ponto de pausa e conclusão aos 100 m.
- [x] Overlay exclusivo no Rhino e independente do foco; movimento/redimensionamento confirmados pelo utilizador.
- [x] Cores do rumo: até 2º verde sem setas; acima de 2º até 8º amarelo com três setas; acima de 8º vermelho com cinco. Sem destino/dados válidos: cinzento.
- [x] Assistência F8 reposta após os ensaios; tolerância configurável; escalões de curva e comando de travagem de 3 s na chegada. Escalões e chegada confirmados no jogo.

## Decisões e limites

Deteção automática do menu Esc cancelada a pedido do utilizador: usar o botão Overlay. Deteção do lançamento de rigs excluída; gestão manual de rigs conservada. Não há deteção de obstáculos. As coberturas de percurso e radar são distintas e têm cores configuráveis. A largura atual de Cobertura aplica-se a todo o percurso reconstruído.

## Validação

Última execução em 13/09/2026: **115 testes passaram**. Aos 11 testes de favoritos/proteção/mineração juntam-se quatro regressões: Rhino parado com StarSystem vazio nos dois modos, rejeição de outro planeta, seleção nas duas linhas da caixa do depósito e lista com uma única coluna/altura conservada. Os testes de janela e operações usam agora ficheiros temporários de telemetria, sem depender do Status.json real do jogo.

Pré-visualizações Qt fora do ecrã foram inspecionadas para os símbolos, ficha e modo de mineração. O Python instalado foi acessível com execução autorizada fora do sandbox. Não foi feito um teste no jogo nesta alteração; as confirmações manuais acima continuam pendentes. Registo da suite: ../outputs/protection-tests.log.

Consultar [PROJECT_NOTES.md](PROJECT_NOTES.md) para utilização e [GUIA_CODIGO_PT_PT.md](GUIA_CODIGO_PT_PT.md) para organização do código.
