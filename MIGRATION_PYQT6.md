# Migração para PyQt6 — registo histórico

Revisto em 11/09/2026. Este ficheiro resume trabalho concluído; não contém instruções de execução de versões intermédias. Para usar a aplicação, consultar [PROJECT_NOTES.md](PROJECT_NOTES.md). As tarefas pendentes estão em [TODO.md](TODO.md).

## Etapas concluídas

1. Separação de cálculos de coordenadas e navegação num núcleo independente da interface.
2. Criação da janela principal e do mapa em Qt.
3. Migração dos diálogos, ficheiros, depósitos e rigs; integração do overlay no ciclo Qt único.
4. Validação manual pelo utilizador e correções de leitura do Rhino ao abrir mapas, combustível, escala de texto entre monitores e contraste dos números da busca.
5. Criação da entrada principal `rhino_surface_mapper.py` e isolamento da versão anterior em `recovery_tkinter/`, com módulos e imagens próprios.

O problema histórico de misturar os ciclos Tkinter e Qt foi primeiro contornado com um processo separado. Essa solução pertence à recuperação. A aplicação atual utiliza um único QApplication e não importa Tkinter nem a ponte entre processos.

## Evolução posterior

A representação por 72 PNGs foi substituída por `assets/Rhino.svg`, com rotação pelo rumo exato. Os PNGs da raiz e a captura `phase3-preview.png` foram arquivados em `archive/obsolete-images-2026-09-10/`; os recursos da recuperação foram conservados.

Foram acrescentados marcas, AZ Busca, entradas compactas e radar com leitura passiva dos controlos do jogo. O diálogo inicial Opções foi posteriormente substituído pelo painel Configurações. A consulta de telemetria passou de 500 para 50 ms; entrada/animação do radar utilizam 16 ms. As descrições atuais estão nas notas do projeto.

## Estado final da migração

A aplicação principal é PyQt6 e a organização da recuperação está concluída. Cobertura contínua e Navegar foram implementados posteriormente; personalização da blindagem e layout da proposta 3 também estão implementados. O painel Configurações inclui persistência e Guardar/Carregar/Repor; setas e cores foram corrigidas e confirmadas pelo utilizador. As validações restantes estão na TODO.

Os resultados de 15 a 27 testes referidos durante o desenvolvimento correspondiam às suites dessas etapas. Para a verificação atual consultar PROJECT_NOTES.md; os resultados históricos não representam a suite atual.

Os dois ZIPs em `../reference-archives/` permanecem intactos. O protótipo `../overlay-prototype/` continua separado da aplicação principal.
