# Contributing

Thank you for helping improve Rhino Surface Mapper.

## Issues and pull requests

Please use [GitHub Issues](https://github.com/pbgaspar/rhino-surface-mapper/issues)
for reproducible bugs, feature ideas, and questions. Pull requests should
explain the user-visible change and include focused tests when behaviour is
changed.

## Development

Use the existing project virtual environment and install the development
requirements from the repository root:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -ra
```

Source code, comments, documentation, and new technical identifiers should be
written in English. Translation contributions should preserve the Qt Linguist
workflow and include the relevant Portuguese catalogue updates.

The project is distributed under the GNU GPL-3.0; see [LICENSE](LICENSE).
