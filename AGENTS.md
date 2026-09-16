# AGENTS.md

## Diretrizes de arquitetura e desenvolvimento para o projeto Rhino Surface Mapper

Este projeto deve seguir uma arquitetura Python clara, modular e sustentável. Prioriza qualidade, previsibilidade e manutenção a longo prazo.

### 1. Modularidade extrema
- Divide o código em módulos pequenos e com responsabilidade única.
- Mantém cada ficheiro focado numa área bem definida: domínio, interface, utilitários, serviços, persistência e testes.
- Evita ficheiros "mega-módulos" com lógica misturada e dezenas de responsabilidades.
- Antes de qualquer alteração futura, analisa a estrutura existente e reutiliza a organização já adotada no projeto.
- Só cria novos módulos quando a separação traz clareza real; caso contrário, mantém a composição atual.

### 2. DRY (Don't Repeat Yourself)
- Reúne lógica repetida em helpers, utilitários ou funções compartilhadas.
- Evita duplicação de regras de negócio, validações, normalização e processamento de dados.
- Quando a mesma lógica aparecer em vários pontos, extrai-a para um local central.
- Procura reutilizar funções e classes já existentes antes de duplicar comportamento.

### 3. Separação de responsabilidades
- Mantém claramente separadas:
  - lógica de negócio
  - interface do utilizador
  - persistência e acesso a dados
  - utilidades gerais
  - testes
- A lógica de negócio não deve depender diretamente de detalhes de UI.
- A interface deve consumir serviços e regras do domínio, não misturar regras de negócio com widgets, eventos ou apresentação.
- O acesso a ficheiros, JSON, CSV, cache e dados externos deve ficar isolado em camadas apropriadas.

### 4. Código limpo e legível
- Escreve código simples, explícito e consistente.
- Usa nomes significativos para funções, classes, variáveis e módulos.
- Mantém funções curtas e com um objetivo bem definido.
- Evita comentários redundantes; prefere código autoexplicativo.
- Documenta a intenção de partes complexas ou não óbvias com docstrings claras e concisas.

### 5. Docstrings e documentação mínima
- Todas as funções, classes e módulos relevantes devem ter docstrings quando a sua finalidade não for óbvia.
- As docstrings devem explicar:
  - o objetivo
  - parâmetros principais
  - comportamentos relevantes
  - exceções esperadas ou resultados importantes
- Prefere documentação útil e objetiva em vez de texto genérico.

### 6. Tratamento robusto de exceções
- Captura exceções específicas, nunca genéricas sem necessidade.
- Evita mascarar erros importantes com blocos broad except.
- Logging e mensagens de erro devem ser informativos e úteis para diagnóstico.
- Preserva a causa real do problema quando repropagar exceções.
- Em entradas externas, dados incompletos ou falhas de I/O, usa tratamento explícito e previsível.

### 7. Testes automatizados
- Prioriza testes automatizados com pytest.
- Os testes devem cobrir a lógica crítica de negócio, regressões e comportamentos sensíveis.
- Mantém os testes simples, determinísticos e focados em comportamento real.
- Sempre que houver correção ou alteração de comportamento, considera adicionar ou ajustar testes.
- Sempre que for criado um novo módulo ou alterada lógica relevante, cria ou atualiza obrigatoriamente os testes automatizados correspondentes, preferencialmente com pytest.
- O código deve ser testável; evita dependências excessivas e acoplamento forte.

### 8. Estrutura coerente de ficheiros e pastas
- Mantém a organização do projeto consistente com a intenção funcional do código.
- Agrupa módulos por responsabilidade e por domínio, em vez de criar dispersão arbitrária.
- Reutiliza convenções já existentes no repositório antes de introduzir novas.
- Evita renomeações ou reorganizações de ficheiros sem necessidade.
- Sempre que uma solução implicar alterações estruturais, apresenta primeiro a estrutura de ficheiros/pastas proposta.

### 9. Refatoração prudente
- Antes de alterar a estrutura do código, analisa primeiro o cenário atual e a arquitetura já existente.
- Reaproveita módulos, funções e padrões já presentes.
- Evita refatorizações desnecessárias, grandes rearranjos ou “limpeza” excessiva sem uma necessidade clara.
- Só refatora quando isso melhora clareza, reduz duplicação ou facilita manutenção sem introduzir riscos indevidos.

### 10. Boas práticas de engenharia Python
- Usa tipos e convenções Pythonic quando fizer sentido.
- Segue padrões consistentes de naming, imports e organização.
- Evita código acoplado, global state desnecessário e efeitos colaterais ocultos.
- Valida entradas e limites de forma explícita quando relevante.
- Mantém o código previsível e fácil de depurar.

## Regra principal
A prioridade é construir software claro, testável e sustentável, respeitando a estrutura existente do projeto e evitando mudanças expansivas sem necessidade.

A arquitetura deve ser simples de seguir, mas suficientemente robusta para crescer sem degradação de qualidade.
