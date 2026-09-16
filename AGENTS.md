# AGENTS.md

## Architecture and development guidelines for the Rhino Surface Mapper project

This project must follow a clear, modular, and sustainable Python architecture. It prioritizes quality, predictability, and long-term maintainability.

### 1. Extreme modularity
- Divide the code into small modules with a single responsibility.
- Keep each file focused on a well-defined area: domain, interface, utilities, services, persistence, and tests.
- Avoid "mega-modules" with mixed logic and dozens of responsibilities.
- Before any future change, analyze the existing structure and reuse the organization already adopted in the project.
- Create new modules only when separation provides real clarity; otherwise, keep the current composition.

### 2. DRY (Don't Repeat Yourself)
- Consolidate repeated logic in helpers, utilities, or shared functions.
- Avoid duplicating business rules, validations, normalization, and data processing.
- When the same logic appears in multiple places, extract it to a central location.
- Look for existing functions and classes to reuse before duplicating behavior.

### 3. Separation of responsibilities
- Keep the following clearly separated:
  - business logic
  - user interface
  - persistence and data access
  - general utilities
  - tests
- Business logic must not depend directly on UI details.
- The interface must consume services and domain rules, without mixing business rules with widgets, events, or presentation.
- Access to files, JSON, CSV, cache, and external data must be isolated in appropriate layers.

### 4. Clean and readable code
- Write simple, explicit, and consistent code.
- Use meaningful names for functions, classes, variables, and modules.
- Keep functions short and focused on a well-defined purpose.
- Avoid redundant comments; prefer self-explanatory code.
- Document the intent of complex or non-obvious parts with clear and concise docstrings.

### 5. Docstrings and minimal documentation
- All relevant functions, classes, and modules must have docstrings when their purpose is not obvious.
- Docstrings must explain:
  - the purpose
  - key parameters
  - relevant behavior
  - expected exceptions or important results
- Prefer useful and objective documentation over generic text.

### Language and comments
- English is the standard language for source-code comments, docstrings, developer-facing technical text, and new technical identifiers.
- Comments should be concise and useful.
- Comments should primarily explain intent, rationale, constraints, invariants, workarounds, or non-obvious behavior.
- Do not add comments merely to restate straightforward code.
- Docstrings must be useful and proportional to the complexity and public role of the function, class, or module; avoid verbose docstrings that merely repeat obvious signatures or implementation details.
- When modifying existing code, non-English comments/docstrings directly related to the changed code may be translated or improved when this remains a small, relevant part of the task.
- Do not perform repository-wide translation or comment/docstring cleanup as a side effect of an unrelated task.
- Existing non-English comments/docstrings elsewhere in the repository do not need to be changed merely because they are encountered.

### 6. Robust exception handling
- Catch specific exceptions, never generic ones without necessity.
- Avoid masking important errors with broad except blocks.
- Logging and error messages must be informative and useful for diagnosis.
- Preserve the actual cause of the problem when re-raising exceptions.
- For external inputs, incomplete data, or I/O failures, use explicit and predictable handling.

### 7. Automated tests
- Prioritize automated tests with pytest.
- Tests must cover critical business logic, regressions, and sensitive behavior.
- Keep tests simple, deterministic, and focused on actual behavior.
- Whenever there is a bug fix or behavior change, consider adding or adjusting tests.
- Whenever a new module is created or relevant logic is changed, the corresponding automated tests must be created or updated, preferably with pytest.
- Code must be testable; avoid excessive dependencies and tight coupling.

### 8. Coherent file and folder structure
- Keep the project organization consistent with the functional purpose of the code.
- Group modules by responsibility and domain instead of creating arbitrary dispersion.
- Reuse conventions already present in the repository before introducing new ones.
- Avoid file renames or reorganizations without necessity.
- Whenever a solution involves structural changes, present the proposed file/folder structure first.

### 9. Careful refactoring
- Before changing the code structure, first analyze the current situation and the existing architecture.
- Reuse existing modules, functions, and patterns.
- Avoid unnecessary refactoring, large rearrangements, or excessive "cleanup" without a clear need.
- Refactor only when it improves clarity, reduces duplication, or facilitates maintenance without introducing undue risk.

### 10. Python engineering best practices
- Use types and Pythonic conventions when appropriate.
- Follow consistent naming, import, and organizational patterns.
- Avoid tightly coupled code, unnecessary global state, and hidden side effects.
- Validate inputs and limits explicitly when relevant.
- Keep the code predictable and easy to debug.

## Main rule
The priority is to build clear, testable, and sustainable software while respecting the existing project structure and avoiding expansive changes without necessity.

The architecture must be simple to follow, but robust enough to grow without degradation in quality.
