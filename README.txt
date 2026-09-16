Rhino Surface Mapper — versão principal PyQt6

Arranque (nesta pasta):
    py -3.13 rhino_surface_mapper.py

Dependências, se necessário:
    py -3.13 -m pip install -r requirements.txt

O comando anterior rhino_surface_mapper_qt.py continua funcional.

Código atual: rhino_surface_mapper.py, rhino_surface_mapper_qt.py,
mapper_core.py, qt_map_operations.py e pyqt_overlay.py.

Recuperação: recovery_tkinter contém a versão anterior, incluindo os seus
módulos e as 72 imagens, sem depender dos módulos atuais.
Arranque da versão anterior, a partir desta pasta:
    py -3.13 recovery_tkinter/rhino_surface_mapper_v2.py

Abrir mapa e Guardar mapa usam por defeito a pasta MAPAS junto ao programa,
mesmo quando iniciado a partir de outra pasta. Pode escolher outra localização.
Os ZIPs de referência não foram alterados.
Para aprender o código: GUIA_CODIGO_PT_PT.md.
