# GitHub Copilot — Rhino Surface Mapper

Segue obrigatoriamente as regras arquiteturais e de engenharia definidas no `AGENTS.md` existente na raiz do projeto.

Ao gerar, completar, modificar ou sugerir código Python:

- Analisa primeiro o código e a estrutura existentes.
- Reutiliza funções, classes e módulos existentes antes de criar novos componentes.
- Não dupliques lógica.
- Mantém funções, classes e módulos pequenos, focados e com responsabilidade única.
- Mantém separadas lógica de negócio, interface e persistência/I/O.
- Preserva o comportamento existente salvo indicação explícita em contrário.
- Não introduzas refatorizações, renomeações ou reorganizações não necessárias para a tarefa.
- Usa tratamento explícito de exceções específicas; nunca uses `except: pass`.
- Usa type hints e docstrings concisas quando apropriado.
- Segue PEP 8 e as convenções já existentes no projeto.
- Escreve código testável.
- Ao criar um módulo ou alterar lógica relevante, cria ou atualiza os testes pytest correspondentes.
- Faz apenas as alterações necessárias para cumprir o pedido.

Em caso de dúvida ou conflito sobre arquitetura ou práticas de engenharia, segue o `AGENTS.md`.
