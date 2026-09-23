"""Entry point for Rhino Surface Mapper, implemented with PySide6.

Executar nesta pasta: py -3.13 rhino_surface_mapper.py
A construção da janela está separada para poder ser importada pelos testes.
"""
from rhino_surface_mapper_qt import main

if __name__ == '__main__':
    raise SystemExit(main())
