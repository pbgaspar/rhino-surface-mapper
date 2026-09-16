# Recuperação — versão anterior em Tkinter

Esta pasta conserva a versão anterior do programa com o overlay Qt num processo separado. Contém cópias dos módulos partilhados e dos 72 ícones para que futuras alterações no código principal não alterem esta versão.

A partir de rhino-surface-mapper:

```powershell
py -3.13 recovery_tkinter/rhino_surface_mapper_v2.py
```

Requer Python com Tkinter e PyQt6 instalados. A pasta principal já não contém o antigo ponto de entrada. Para uso normal, executar `py -3.13 rhino_surface_mapper.py` na pasta principal.

Apenas os imports foram adaptados para esta separação; o comportamento anterior foi conservado. Os testes da versão antiga importam este pacote.

Revisto em 10/09/2026: os 72 PNGs desta pasta continuam necessários a esta versão. O arquivo dos PNGs da raiz não alterou estes recursos. A aplicação principal usa `assets/Rhino.svg` e não importa este pacote.
