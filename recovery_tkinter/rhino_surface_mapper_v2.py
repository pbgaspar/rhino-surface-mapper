"""
Rhino Surface Mapper v2
========================

Programa auxiliar para Elite Dangerous que lê a posição do SRV Rhino a partir
do Status.json e apresenta um mapa local da superfície planetária.

NOTA:
Este ficheiro é uma versão COMENTADA do programa. Os comentários e docstrings
explicam a intenção de cada função e dos principais blocos, sem alterar a
lógica funcional da versão validada.
"""

# Bibliotecas usadas:
# - json: leitura/escrita do Status.json e dos mapas guardados
# - math: cálculos de distâncias, rumos e conversão de coordenadas
# - time: timestamp de segurança para os pontos
import json, math, time, sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Importações relativas quando usado pelos testes; locais no arranque direto.
if __package__:
    from .overlay_process import OverlayProcess
    from .mapper_core import MapperState
else:
    from overlay_process import OverlayProcess
    from mapper_core import MapperState

APP_TITLE = "Rhino Surface Mapper v2"
DEFAULT_STATUS = Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous" / "Status.json"
SRV_FLAG = 0x04000000

# -----------------------------------------------------------------------------
# Classe principal da aplicação. Guarda o estado do mapa e trata da interface,
# leitura do jogo, navegação e desenho no Canvas.
# -----------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root=root; root.title(APP_TITLE); root.geometry("1150x800")
        self.status_path=DEFAULT_STATUS
        self.points=[]; self.deposits=[]; self.rigs=[]
        self.system=""; self.body=""; self.body_key=None
        self.center_lat=None; self.center_lon=None; self.radius=6371000
        self.last_xy=None; self.last_mtime=0
        self.rhino_lat=None; self.rhino_lon=None
        self.search_started=False; self.datum_lat=None; self.datum_lon=None
        self.route_index=0; self.next_target_xy=None
        # Histórico dos destinos da busca: cada entrada guarda número, posição e estado (alcançado/saltado).
        self.route_history=[]
        self.rhino_heading=None
        self.overlay=None
        self.overlay_mode_active=False
        self.overlay_blink_on=True
        self.overlay_next_blink=0.0
        self.overlay_error_shown=False
        root.protocol("WM_DELETE_WINDOW", self.exit_app)

        # Ícones pré-rodados do Rhino. São carregados uma vez para evitar
        # depender de bibliotecas externas durante a execução do programa.
        self.rhino_icons=[]
        self._load_rhino_icons()

        self.width=tk.DoubleVar(value=2000)
        self.scanner=tk.DoubleVar(value=2000)
        self.info=tk.StringVar(value="Rhino Surface Mapper v2")
        self.fuel_reservoir=None; self.fuel_percent=None; self.fuel_low=False
        self._ui(); root.after(500,self.poll)

    # -------------------------------------------------------------------------
    # Carrega os ícones do Rhino pré-rodados em passos de 5 graus.
    # 000° corresponde ao Rhino virado para Norte; os restantes acompanham
    # o Heading recebido do Elite Dangerous.
    # -------------------------------------------------------------------------
    def _load_rhino_icons(self):
        base=Path(__file__).resolve().parent
        for deg in range(0,360,5):
            p=base / f"rhino_{deg:03d}.png"
            try:
                self.rhino_icons.append(tk.PhotoImage(file=str(p)))
            except Exception:
                self.rhino_icons.append(None)

    # -------------------------------------------------------------------------
    # Escolhe o ícone mais próximo do Heading atual.
    # -------------------------------------------------------------------------
    def _rhino_icon_for_heading(self):
        if not self.rhino_icons or self.rhino_heading is None:
            return None
        idx=int((self.rhino_heading+2.5)//5)%72
        return self.rhino_icons[idx]

    # -------------------------------------------------------------------------
    # Construção da interface gráfica
    # -------------------------------------------------------------------------
    def _ui(self):
        bar=ttk.Frame(self.root,padding=8); bar.pack(fill="x")
        ttk.Label(bar,text="Cobertura (m):").pack(side="left")
        ttk.Spinbox(bar,from_=100,to=5000,increment=100,textvariable=self.width,width=7).pack(side="left",padx=4)
        ttk.Label(bar,text="Scanner (m):").pack(side="left",padx=(12,0))
        ttk.Spinbox(bar,from_=500,to=5000,increment=100,textvariable=self.scanner,width=7).pack(side="left",padx=4)
        ttk.Button(bar,text="Novo mapa",command=self.new).pack(side="left",padx=5)
        ttk.Button(bar,text="Guardar",command=self.save).pack(side="left",padx=5)
        ttk.Button(bar,text="Abrir",command=self.load).pack(side="left",padx=5)
        ttk.Button(bar,text="Marcar depósito",command=self.mark_deposit).pack(side="left",padx=5)
        ttk.Button(bar,text="Marcar rig",command=self.mark_rig).pack(side="left",padx=5)
        ttk.Button(bar,text="Escolher Status.json",command=self.choose).pack(side="left",padx=5)
        ttk.Button(bar,text="Iniciar busca",command=self.start_search).pack(side="left",padx=5)
        ttk.Button(bar,text="Saltar próximo",command=self.skip_next).pack(side="left",padx=5)
        self.overlay_button=ttk.Button(bar,text="Overlay",command=self.toggle_overlay,state="disabled")
        self.overlay_button.pack(side="left",padx=5)
        right_controls=ttk.Frame(bar)
        right_controls.pack(side="right")
        ttk.Button(right_controls,text="Sair",command=self.exit_app).pack(side="top",padx=5)
        self.center_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(right_controls,text="Centrar",variable=self.center_var).pack(side="top",padx=5)
        self.fuelinfo=tk.StringVar(value="FUEL : —")
        # O modo ativo controla a disponibilidade e abertura do overlay.

        info_bar=ttk.Frame(self.root,padding=(8,0))
        info_bar.pack(fill="x")
        ttk.Label(info_bar,textvariable=self.info).pack(side="left")
        ttk.Label(info_bar,textvariable=self.fuelinfo,anchor="e").pack(side="right")

        self.canvas=tk.Canvas(self.root,bg="white")
        self.canvas.pack(fill="both",expand=True,padx=8,pady=8)
        self.canvas.bind("<Configure>",lambda e:self.draw())
        self.canvas.bind("<Button-1>",self.click)
        self.canvas.bind("<Button-2>",lambda e:self.recenter_rhino())
        self.canvas.bind("<Button-3>",self.right_press_event)
        self.canvas.bind("<B3-Motion>",self.right_drag_event)
        self.canvas.bind("<ButtonRelease-3>",self.right_release_event)
        self.canvas.bind("<MouseWheel>",self.mousewheel_zoom)
        self.canvas.bind("<Button-4>",lambda e:self.zoom_at(e.x,e.y,1.15))
        self.canvas.bind("<Button-5>",lambda e:self.zoom_at(e.x,e.y,1/1.15))
        self.canvas.bind("<Motion>",self.update_cursor_info)
        self.root.bind("<KeyPress-plus>",lambda e:self.zoom_center(1.15))
        self.root.bind("<KeyPress-equal>",lambda e:self.zoom_center(1.15))
        self.root.bind("<KeyPress-minus>",lambda e:self.zoom_center(1/1.15))
        self.root.bind("<KeyPress-Home>",lambda e:self.recenter_rhino())
        self.root.bind("<KeyPress-KP_Add>",lambda e:self.zoom_center(1.15))
        self.root.bind("<KeyPress-KP_Subtract>",lambda e:self.zoom_center(1/1.15))

        statusbar=ttk.Frame(self.root,padding=(8,4))
        statusbar.pack(fill="x")
        self.nextinfo=tk.StringVar(value="Sec. Sugerido: —")
        self.cursorinfo=tk.StringVar(value="Cursor: —")
        self.distinfo=tk.StringVar(value="Dist.: —")
        self.azinfo=tk.StringVar(value="Azimute: —")
        ttk.Label(statusbar,textvariable=self.nextinfo).pack(side="left")
        rightinfo=ttk.Frame(statusbar)
        rightinfo.pack(side="right")
        ttk.Label(rightinfo,textvariable=self.cursorinfo).pack(side="left",padx=(0,12))
        ttk.Label(rightinfo,textvariable=self.distinfo).pack(side="left",padx=(0,12))
        ttk.Label(rightinfo,textvariable=self.azinfo).pack(side="left")

    # Escolhe manualmente outro Status.json.
    def choose(self):
        p=filedialog.askopenfilename(filetypes=[("JSON","*.json"),("Todos","*.*")])
        if p:
            self.status_path=Path(p)
            self.last_mtime=None
            self.info.set(f"Status: {p}")

    # Cria um mapa novo, mantendo a posição/fuel atuais do Rhino.
    def new(self):
        if self.points and not messagebox.askyesno("Novo mapa","Apagar o mapa atual?"):return
        # Start a new map, but keep the last live Rhino/planet/fuel state so the
        # map immediately looks like it does after the first Status.json update.
        self.points=[];self.deposits=[];self.rigs=[];self.last_xy=None
        self.search_started=False; self.datum_lat=None; self.datum_lon=None
        self.route_index=0; self.next_target_xy=None
        self.route_history=[]
        self.nextinfo.set("Sec. Sugerido: —")
        self.zoom=1.0; self.view_center=None; self.view_user_controlled=False; self.base_scale=None
        if self.rhino_lat is not None and self.rhino_lon is not None and self.center_lat is not None:
            self.info.set(f"{self.system} — {self.body} | Lat {self.rhino_lat:.5f}° Lon {self.rhino_lon:.5f}° | "
                          f"Pontos 0 | Cobertura {self.width.get():.0f} m")
        self.draw()
        self.update_overlay()
        if self.canvas.winfo_width()>1 and self.canvas.winfo_height()>1:
            self.update_cursor_info_xy(self.canvas.winfo_width()//2,self.canvas.winfo_height()//2)

    # Fixa o Datum na posição atual e inicia a estratégia de procura circular.
    def start_search(self):
        # The current Rhino position becomes the fixed Datum (search centre).
        if self.rhino_lat is None or self.rhino_lon is None or self.center_lat is None:
            messagebox.showinfo("Iniciar busca", "Primeiro entra no Rhino e aguarda a posição ser detetada.")
            return
        if self.search_started:
            if not messagebox.askyesno("Iniciar busca", "A busca já foi iniciada. Substituir o Datum atual pela posição do Rhino? "):
                return
        self.datum_lat = self.rhino_lat
        self.datum_lon = self.rhino_lon
        self.search_started = True
        self.route_index = 0
        self.next_target_xy = None
        self.route_history = []
        # Show the first destination immediately, without waiting for movement.
        self.update_next()
        self.info.set(f"{self.system} — {self.body} | Lat {self.rhino_lat:.5f}° Lon {self.rhino_lon:.5f}° | "
                      f"Pontos {len(self.points)} | Datum definido")
        self.draw()
        self.update_overlay()

    # Salta o destino atual da busca e passa imediatamente para o seguinte.
    # O destino não é considerado alcançado: fica registado no histórico a vermelho.
    def skip_next(self):
        if not self.search_started or self.datum_lat is None or self.next_target_xy is None:
            messagebox.showinfo("Saltar próximo", "Não existe um próximo destino de busca para saltar.")
            return

        # O número apresentado no mapa é o número da posição da sequência circular.
        number = self.route_index + 1
        tx, ty = self.next_target_xy
        self.route_history.append({
            "number": number,
            "x": tx,
            "y": ty,
            "status": "skipped"
        })

        # Recomeça a numeração da próxima posição pelo índice seguinte.
        self.route_index += 1
        radius = 3500.0
        spacing = 1800.0
        total_points = max(1, math.ceil((2.0 * math.pi * radius) / spacing))
        if self.route_index >= total_points:
            self.next_target_xy = None
            self.nextinfo.set("Sec. Sugerido: Procura circular concluída")
        else:
            self.update_next()
        self.draw()
        self.update_overlay()

    # -------------------------------------------------------------------------
    # OVERLAY DE NAVEGAÇÃO (PyQt6)
    # -------------------------------------------------------------------------
    def create_overlay(self):
        """Abre Qt num processo independente do Tkinter."""
        try:
            if self.overlay is not None and self.overlay.process.is_alive():
                self.overlay.show()
            else:
                if self.overlay is not None:
                    self.overlay.close()
                self.overlay = OverlayProcess()
            self.update_overlay()
        except Exception as exc:
            self.overlay = None
            messagebox.showerror("Overlay indisponível", str(exc))

    def hide_overlay(self):
        """Esconde o overlay sem fechar o Mapper."""
        if self.overlay is not None:
            try: self.overlay.hide()
            except Exception: pass

    def show_overlay(self):
        """Mostra novamente o overlay."""
        if self.overlay is None or not self.overlay.process.is_alive():
            self.create_overlay()
            return
        try:
            self.overlay.show()
            self.overlay.raise_()
            self.update_overlay()
        except Exception:
            pass

    def toggle_overlay(self):
        """Mostra/esconde o overlay através do botão da interface principal."""
        if not MapperState.overlay_allowed(self):
            return
        if self.overlay is None or not self.overlay.process.is_alive():
            self.create_overlay()
            return
        try:
            if self.overlay.isVisible(): self.hide_overlay()
            else: self.show_overlay()
        except Exception:
            self.create_overlay()

    _heading_error = staticmethod(MapperState.heading_error)

    def update_overlay(self):
        """Atualiza rumo, setas, cor e distância mostrados no overlay."""
        navigation = MapperState.overlay_navigation(self)
        allowed = MapperState.overlay_allowed(self)
        was_active = getattr(self, "overlay_mode_active", allowed)
        self.overlay_mode_active = allowed
        if hasattr(self, "overlay_button"):
            self.overlay_button.configure(state="normal" if allowed else "disabled")
        if not allowed:
            if self.overlay is not None:
                self.hide_overlay()
            return
        if not was_active:
            self.create_overlay()
        if self.overlay is None:
            return
        if isinstance(self.overlay, OverlayProcess) and not self.overlay.process.is_alive():
            self.overlay.close()
            self.overlay = None
            self.info.set("O overlay terminou. Usa o botão Overlay para reabrir.")
            return

        try:
            self.overlay.set_navigation(*navigation)
        except (OSError, RuntimeError):
            self.info.set("O overlay não respondeu. Usa o botão Overlay para reabrir.")

    # Verifica periodicamente se o Status.json foi alterado.
    def poll(self):
        try:
            m=self.status_path.stat().st_mtime_ns
            if m!=self.last_mtime:
                s=json.loads(self.status_path.read_text(encoding="utf-8"))
                self.process(s)
                self.last_mtime=m
        except Exception: pass
        self.update_overlay()
        self.root.after(500,self.poll)

    # Processa uma leitura do Status.json quando o Rhino está em utilização.
    def process(self,s):
        if not (int(s.get("Flags",0)) & SRV_FLAG): return
        fuel=s.get("Fuel") or {}
        reservoir=fuel.get("FuelReservoir")
        if reservoir is not None:
            self.fuel_reservoir=float(reservoir)
            self.fuel_percent=max(0.0,min(100.0,self.fuel_reservoir/0.80*100.0))
            low_flag=bool(int(s.get("Flags",0)) & 0x00080000)
            self.fuel_low=low_flag
            if self.fuel_percent <= 0:
                self.fuelinfo.set("FUEL : 0% ⛔ Sem combustível")
            elif self.fuel_percent <= 15:
                self.fuelinfo.set(f"FUEL : {self.fuel_percent:.0f}% 🔴 Crítico")
            elif self.fuel_percent <= 30:
                self.fuelinfo.set(f"FUEL : {self.fuel_percent:.0f}% ⚠ Baixo")
            else:
                self.fuelinfo.set(f"FUEL : {self.fuel_percent:.0f}% ✓ Normal")
        # Heading é o rumo atual do Rhino, em graus, fornecido pelo jogo.
        heading=s.get("Heading")
        if heading is not None:
            try:
                self.rhino_heading=float(heading)%360.0
            except Exception:
                self.rhino_heading=None
        lat=s.get("Latitude"); lon=s.get("Longitude")
        if lat is None or lon is None:return
        self.rhino_lat=float(lat); self.rhino_lon=float(lon)
        body=s.get("BodyName",""); system=s.get("StarSystem","")
        key=f"{system}|{body}"
        if self.body_key!=key:
            self.body_key=key;self.system=system;self.body=body
            self.center_lat=float(lat);self.center_lon=float(lon)
            self.radius=float(s.get("PlanetRadius") or 6371000)
            self.points=[];self.deposits=[];self.rigs=[];self.last_xy=None
            self.zoom=1.0; self.view_center=None; self.view_user_controlled=False; self.base_scale=None
        x,y=self.llxy(float(lat),float(lon))
        if self.center_var.get():
            self.view_center=(x,y)
            self.view_user_controlled=True
        if self.last_xy is None or math.hypot(x-self.last_xy[0],y-self.last_xy[1])>=10:
            jump = self.last_xy is not None and math.hypot(x-self.last_xy[0],y-self.last_xy[1]) > 100.0
            point = {"x":x,"y":y,"lat":float(lat),"lon":float(lon),"t":s.get("timestamp",time.time())}
            if jump:
                point["break_before"] = True
            self.points.append(point)
            self.last_xy=(x,y)
        self.info.set(f"{system} — {body} | Lat {float(lat):.5f}° Lon {float(lon):.5f}° | "
                      f"Pontos {len(self.points)} | Cobertura {self.width.get():.0f} m")
        self.update_next();self.draw();self.update_overlay()

    # Regras partilhadas com a futura interface Qt, sem dependências gráficas.
    llxy = MapperState.llxy
    xyll = MapperState.xyll

    # Calcula os limites do mapa que devem ficar visíveis.
    def bounds(self):
        ps=[(p["x"],p["y"]) for p in self.points]
        if not ps:return -2000,2000,-2000,2000
        xs=[p[0] for p in ps];ys=[p[1] for p in ps];m=max(1000,self.width.get()*3)
        return min(xs)-m,max(xs)+m,min(ys)-m,max(ys)+m

    # Calcula escala e deslocamento para converter metros em pixels do Canvas.
    def transform(self):
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        x0,x1,y0,y1=self.bounds()
        base_sc=min((w-70)/(x1-x0),(h-70)/(y1-y0))
        if self.view_center is None:
            self.view_center=((x0+x1)/2,(y0+y1)/2)
        if self.base_scale is None or not self.view_user_controlled:
            self.base_scale=base_sc
        sc=self.base_scale*self.zoom
        cx,cy=self.view_center
        ox=w/2-cx*sc; oy=h/2+cy*sc
        return sc,ox,oy

    # Atalho: converte uma posição do mapa para posição no ecrã.
    def S(self,x,y):
        sc,ox,oy=self.transform();return ox+x*sc,oy-y*sc

    # Procura um depósito ou rig próximo do ponto clicado.
    def _marker_at(self,e):
        if self.center_lat is None:
            return None
        best=None;best_px=12
        for i,d in enumerate(self.deposits):
            qx,qy=self.S(d["x"],d["y"])
            dist=math.hypot(e.x-qx,e.y-qy)
            if dist<=best_px:
                best=("deposit",i);best_px=dist
        for i,r in enumerate(self.rigs):
            qx,qy=self.S(r["x"],r["y"])
            dist=math.hypot(e.x-qx,e.y-qy)
            if dist<=best_px:
                best=("rig",i);best_px=dist
        return best

    # Faz zoom mantendo fixa no ecrã a posição que está debaixo do cursor.
    def zoom_at(self,sx,sy,factor):
        if self.center_lat is None:return
        old_sc,old_ox,old_oy=self.transform()
        mx=(sx-old_ox)/old_sc; my=(old_oy-sy)/old_sc
        self.zoom=max(0.15,min(20.0,self.zoom*factor))
        new_sc,_,_=self.transform()
        # Keep the map coordinate under the cursor fixed on screen.
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        self.view_center=(mx+(w/2-sx)/new_sc, my+(sy-h/2)/new_sc)
        self.view_user_controlled=True
        self.draw()
        self.update_cursor_info_xy(sx,sy)

    # Faz zoom usando o centro atual do mapa.
    def zoom_center(self,factor):
        self.zoom=max(0.15,min(20.0,self.zoom*factor))
        self.view_user_controlled=True
        self.draw()

    # Trata o zoom da roda do rato.
    def mousewheel_zoom(self,e):
        self.zoom_at(e.x,e.y,1.15 if e.delta>0 else 1/1.15)

    # Centra o mapa na posição atual/conhecida do Rhino.
    def recenter_rhino(self):
        if not self.points:return
        p=self.points[-1]
        self.view_center=(p["x"],p["y"])
        self.view_user_controlled=True
        self.draw()

    # Inicia uma operação com o botão direito: menu contextual ou pan.
    def right_press_event(self,e):
        if self.center_lat is None:return
        marker=self._marker_at(e)
        self.right_press=(e.x,e.y)
        self.right_press_marker=marker is not None
        if marker:
            self.right_click(e,marker)
        else:
            self.pan_start=(e.x,e.y)
            self.pan_center_start=self.view_center or (0,0)

    # Move o mapa quando o botão direito está a ser arrastado.
    def right_drag_event(self,e):
        if self.pan_start is None or self.center_lat is None:return
        dx=e.x-self.pan_start[0];dy=e.y-self.pan_start[1]
        sc,_,_=self.transform()
        cx,cy=self.pan_center_start
        self.view_center=(cx-dx/sc,cy+dy/sc)
        self.view_user_controlled=True
        self.draw()
        self.update_cursor_info(e)

    # Termina o pan/menu iniciado com o botão direito.
    def right_release_event(self,e):
        self.pan_start=None; self.pan_center_start=None; self.right_press=None; self.right_press_marker=False

    # Atualiza as informações relativas ao cursor do rato.
    def update_cursor_info(self,e):
        self.update_cursor_info_xy(e.x,e.y)

    # Calcula coordenadas, distância e azimute para a posição do cursor.
    def update_cursor_info_xy(self,sx,sy):
        if self.center_lat is None or (not self.points and (self.rhino_lat is None or self.rhino_lon is None)):
            self.cursorinfo.set("Cursor: —");self.distinfo.set("Dist.: —");self.azinfo.set("Azimute: —");return
        sc,ox,oy=self.transform()
        if sc<=0:return
        x=(sx-ox)/sc; y=(oy-sy)/sc
        lat,lon=self.xyll(x,y)
        if self.points:
            p=self.points[-1]
            px,py=p["x"],p["y"]
        else:
            px,py=self.llxy(self.rhino_lat,self.rhino_lon)
        dx=x-px;dy=y-py
        dist=math.hypot(dx,dy)
        az=(math.degrees(math.atan2(dx,dy))+360)%360
        self.cursorinfo.set(f"Cursor: {lat:.5f}°, {lon:.5f}°")
        self.distinfo.set(f"Dist.: {dist:.0f} m")
        self.azinfo.set(f"Azimute: {az:03.0f}°")

    # Fecha a janela e termina a aplicação.
    def exit_app(self):
        if self.overlay is not None:
            try: self.overlay.close()
            except Exception: pass
        self.root.destroy()

    # Desenha todo o mapa: grelha, cobertura, rasto, Datum, PRÓXIMO,
    # scanner, Rhino, depósitos e rigs. O Canvas é redesenhado por completo.
    def draw(self):
        c=self.canvas;c.delete("all")
        if self.center_lat is None:
            c.create_text(c.winfo_width()/2,c.winfo_height()/2,text="Entra no Rhino para começar o mapa.")
            return
        sc,ox,oy=self.transform();x0,x1,y0,y1=self.bounds()
        step=100 if max(x1-x0,y1-y0)<6000 else 1000
        gx=math.floor(x0/step)*step
        while gx<=x1:
            a,b=self.S(gx,y0);d,e=self.S(gx,y1);c.create_line(a,b,d,e,fill="#eeeeee");gx+=step
        gy=math.floor(y0/step)*step
        while gy<=y1:
            a,b=self.S(x0,gy);d,e=self.S(x1,gy);c.create_line(a,b,d,e,fill="#eeeeee");gy+=step

        # ---------------------------------------------------------------------
        # Cobertura e rasto
        #
        # Cada amostra de posição recebe um círculo com o raio de cobertura.
        # Os círculos não têm contorno: isso evita o efeito de "borrão"
        # provocado pelas muitas circunferências sobrepostas.
        #
        # A área verde é uma aproximação visual de uma transparência de cerca
        # de 40%. O Canvas Tkinter não trabalha aqui com alfa verdadeiro, por
        # isso usamos um verde muito claro que se mistura visualmente com o
        # fundo branco.
        #
        # O rasto é desenhado DEPOIS da cobertura, para ficar sempre visível
        # por cima dos círculos.
        # ---------------------------------------------------------------------
        rp=max(2,self.width.get()*sc/2)
        coverage_fill="#edf8ed"
        coverage_points=[]

        # Primeiro desenhamos apenas a cobertura.
        for p in self.points:
            q=self.S(p["x"],p["y"])
            c.create_oval(q[0]-rp,q[1]-rp,q[0]+rp,q[1]+rp,
                          fill=coverage_fill,outline="")
            coverage_points.append((q, p))

        # Durante a busca, desenhamos o percurso real como uma linha verde
        # fina. Só ligamos pontos consecutivos quando não existe uma quebra
        # lógica superior a 100 m.
        if self.search_started:
            prev=None
            for q,p in coverage_points:
                if prev is not None and not p.get("break_before"):
                    c.create_line(prev[0],prev[1],q[0],q[1],
                                  fill="#2f7d32",width=1)
                prev=q

        # Depois do desenho da cobertura/rasto, marcamos os pontos individuais.
        for q,p in coverage_points:
            c.create_oval(q[0]-2,q[1]-2,q[0]+2,q[1]+2,fill="#2f7d32",outline="")

        # Imediatamente depois de Novo mapa, mostramos a posição atual do
        # Rhino e a respetiva cobertura, mesmo antes de surgir o primeiro
        # ponto gravado pelo Status.json.
        if not self.points and self.rhino_lat is not None and self.rhino_lon is not None:
            rx,ry=self.llxy(self.rhino_lat,self.rhino_lon)
            qr=self.S(rx,ry)
            c.create_oval(qr[0]-rp,qr[1]-rp,qr[0]+rp,qr[1]+rp,
                          fill=coverage_fill,outline="")
            c.create_oval(qr[0]-2,qr[1]-2,qr[0]+2,qr[1]+2,fill="#2f7d32",outline="")

        # ---------------------------------------------------------------------
        # Datum: ponto fixo onde a busca foi iniciada.
        # ---------------------------------------------------------------------
        # Datum / search centre.
        if self.datum_lat is not None and self.datum_lon is not None:
            dx,dy=self.llxy(self.datum_lat,self.datum_lon)
            qd=self.S(dx,dy)
            c.create_oval(qd[0]-8,qd[1]-8,qd[0]+8,qd[1]+8,outline="#cc7a00",width=3)
            c.create_line(qd[0]-12,qd[1],qd[0]+12,qd[1],fill="#cc7a00",width=2)
            c.create_line(qd[0],qd[1]-12,qd[0],qd[1]+12,fill="#cc7a00",width=2)
            c.create_text(qd[0]+12,qd[1]+12,text="DATUM",anchor="nw",fill="#cc7a00")

        # ---------------------------------------------------------------------
        # PRÓXIMO: destino atual calculado pela estratégia de procura.
        # ---------------------------------------------------------------------
        # Próximo destino da estratégia de procura.
        if self.next_target_xy is not None:
            tx, ty = self.next_target_xy
            qt = self.S(tx, ty)
            c.create_oval(qt[0]-9, qt[1]-9, qt[0]+9, qt[1]+9, outline="#e08a00", width=3)
            c.create_line(qt[0]-14, qt[1], qt[0]+14, qt[1], fill="#e08a00", width=2)
            c.create_line(qt[0], qt[1]-14, qt[0], qt[1]+14, fill="#e08a00", width=2)
            c.create_text(qt[0]+12, qt[1]-12, text="PRÓXIMO", anchor="sw", fill="#e08a00")
            if self.rhino_lat is not None and self.rhino_lon is not None:
                rx, ry = self.llxy(self.rhino_lat, self.rhino_lon)
                qr = self.S(rx, ry)
                c.create_line(qr[0], qr[1], qt[0], qt[1], fill="#e08a00", dash=(6,4), width=2)

        # ---------------------------------------------------------------------
        # Scanner: círculo tracejado centrado no Rhino.
        # ---------------------------------------------------------------------
        # Scanner circle at current position.
        if self.points:
            p=self.points[-1];rx,ry=p["x"],p["y"]
        elif self.rhino_lat is not None and self.rhino_lon is not None:
            rx,ry=self.llxy(self.rhino_lat,self.rhino_lon)
        else:
            rx=ry=None
        if rx is not None:
            q=self.S(rx,ry);rs=self.scanner.get()*sc
            if rs<min(c.winfo_width(),c.winfo_height())*2:
                c.create_oval(q[0]-rs,q[1]-rs,q[0]+rs,q[1]+rs,outline="#7777aa",dash=(5,4))
            # Em vez do marcador circular genérico, mostramos o Rhino visto
            # de cima. O desenho acompanha o Heading atual do jogo.
            icon=self._rhino_icon_for_heading()
            if icon is not None:
                c.create_image(q[0],q[1],image=icon)
            else:
                # Fallback caso os PNGs não estejam disponíveis.
                c.create_oval(q[0]-6,q[1]-6,q[0]+6,q[1]+6,outline="#cc2222",width=3)
                c.create_text(q[0]+10,q[1]-10,text="RHINO",anchor="sw",fill="#cc2222")

        for d in self.deposits:
            q=self.S(d["x"],d["y"]);c.create_oval(q[0]-7,q[1]-7,q[0]+7,q[1]+7,fill="#c43b3b",outline="")
            label=d.get("name","Depósito")
            size=d.get("size")
            rigs=d.get("rigs")
            details=[]
            if size: details.append(size)
            if rigs: details.append(f"{rigs} rig" + ("s" if int(rigs)!=1 else ""))
            if details: label += " (" + ", ".join(details) + ")"
            c.create_text(q[0]+9,q[1],text=label,anchor="w")
        for r in self.rigs:
            q=self.S(r["x"],r["y"]);c.create_rectangle(q[0]-6,q[1]-6,q[0]+6,q[1]+6,outline="#3333aa",width=2)
            c.create_text(q[0]+9,q[1],text="Rig",anchor="w")

        # ---------------------------------------------------------------------
        # Histórico dos destinos da busca.
        #
        # Os números são desenhados NO FIM, para que nenhum outro elemento do
        # mapa possa ficar por cima deles.
        #
        # Além disso, fazemos primeiro uma versão ligeiramente maior em branco
        # e depois o número na sua cor normal. Esta pequena "auréola" branca
        # aumenta muito a legibilidade quando o rasto ou a cobertura passam
        # por baixo do número. Não usamos uma caixa branca porque seria
        # visualmente mais pesada.
        # ---------------------------------------------------------------------
        for hitem in self.route_history:
            qh = self.S(hitem["x"], hitem["y"])
            if hitem.get("status") == "skipped":
                fill = "#cc2222"
            else:
                fill = "#2f7d32"
            label = f'[{int(hitem["number"])}]'
            # O Tkinter Canvas não possui contorno de texto verdadeiro.
            # Para criar uma auréola branca realmente visível, desenhamos
            # oito cópias brancas muito pequenas à volta do texto e só depois
            # colocamos o texto colorido no centro. Assim o rasto nunca
            # consegue "comer" visualmente o número.
            for ox, oy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(1,-1),(-1,1),(1,1)):
                c.create_text(qh[0]+ox, qh[1]+oy, text=label, anchor="center",
                              fill="white", font=("TkDefaultFont", 10, "bold"))
            c.create_text(qh[0], qh[1], text=label, anchor="center",
                          fill=fill, font=("TkDefaultFont", 10, "bold"))

        c.create_text(10,10,text="N ↑",anchor="nw",fill="#555")
        c.create_text(c.winfo_width()-10,10,text=self.body,anchor="ne",fill="#333")

    # Clique esquerdo normal: atualmente não executa qualquer ação.
    def click(self,e):
        if self.center_lat is None:return
        # Clicking with normal button does nothing; use buttons for unambiguous markers.
        pass

    # Converte coordenadas de ecrã (pixels) para coordenadas do mapa (metros).
    def screen_xy(self,e):
        sc,ox,oy=self.transform();return (e.x-ox)/sc,(oy-e.y)/sc

    # Marca um depósito na posição atual do Rhino e pede os seus dados.
    def mark_deposit(self):
        # A posição é sempre a posição real mais recente do Rhino; não é
        # necessário clicar manualmente no mapa para marcar um depósito.
        if self.rhino_lat is None or self.rhino_lon is None:
            messagebox.showinfo("Depósito", "Primeiro entra no Rhino.")
            return

        lat, lon = self.rhino_lat, self.rhino_lon

        # Prevent duplicate deposits within 80 metres.
        for d in self.deposits:
            dlat = math.radians(lat - float(d.get("lat", 0)))
            dlon = math.radians(lon - float(d.get("lon", 0)))
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(lat)) * math.cos(math.radians(float(d.get("lat", 0)))) *
                 math.sin(dlon / 2) ** 2)
            distance = 2 * self.radius * math.asin(min(1.0, math.sqrt(a)))
            if distance < 80.0:
                messagebox.showinfo("Depósito já marcado", "Depósito já marcado")
                return

        x, y = self.llxy(lat, lon)
        result = self.deposit_editor(self.root, lat, lon)
        if result is None:
            return
        name, size, nrigs = result
        self.deposits.append({"x":x, "y":y, "lat":lat, "lon":lon,
                              "name":name or "Depósito", "size":size, "rigs":nrigs})
        self.draw()

    # Inicia o modo de colocação manual de um rig no mapa.
    def mark_rig(self):
        self.marker_dialog("Rig",self.rigs)

    # Janela temporária usada para colocar um marcador clicando no mapa.
    def marker_dialog(self,kind,target):
        if self.center_lat is None:
            messagebox.showinfo(kind,"Primeiro entra no Rhino.")
            return
        # Only one active marker operation at a time.  The temporary left-click
        # binding is removed whenever the dialog closes or a marker is placed.
        win=tk.Toplevel(self.root);win.title(f"Marcar {kind}");win.transient(self.root)
        ttk.Label(win,text=f"Clica no mapa para colocar {kind}.").pack(padx=20,pady=12)
        active=[True]

        old=self.canvas.bind("<Button-1>")

        def cleanup():
            if not active[0]:
                return
            active[0]=False
            if old:
                self.canvas.bind("<Button-1>",old)
            else:
                self.canvas.unbind("<Button-1>")
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
            except tk.TclError:
                pass

        def place(e):
            if not active[0]:
                return
            x,y=self.screen_xy(e);lat,lon=self.xyll(x,y)
            if kind=="Depósito":
                result=self.deposit_editor(self.root, lat, lon)
                if result is None:
                    return
                name,size,nrigs=result
                target.append({"x":x,"y":y,"lat":lat,"lon":lon,
                               "name":name or "Depósito", "size":size, "rigs":nrigs})
            else:
                target.append({"x":x,"y":y,"lat":lat,"lon":lon})
            self.draw()
            # A marker operation is a single placement.  After OK, close both
            # the name/details dialog and the "Marcar ..." dialog.
            cleanup()

        ttk.Button(win,text="Concluído",command=cleanup).pack(pady=8)
        self.canvas.bind("<Button-1>",place)
        win.protocol("WM_DELETE_WINDOW",cleanup)

    # Edita/cria os dados associados a um depósito.
    def deposit_editor(self,parent,lat=None,lon=None,existing=None):
        title="Editar depósito" if existing is not None else "Nome do depósito"
        w=tk.Toplevel(parent);w.title(title);w.transient(parent);w.grab_set()
        ttk.Label(w,text="Nome do depósito:").pack(anchor="w",padx=15,pady=(12,2))
        name_var=tk.StringVar(value=(existing or {}).get("name", "") if existing else "")
        ent=ttk.Entry(w,textvariable=name_var,width=30);ent.pack(padx=15,fill="x")

        ttk.Label(w,text="Tamanho:").pack(anchor="w",padx=15,pady=(10,2))
        size_var=tk.StringVar(value=(existing or {}).get("size", "Pequeno") if existing else "Pequeno")
        size_box=ttk.Combobox(w,textvariable=size_var,values=["Pequeno","Médio","Grande","Enorme"],state="readonly",width=18)
        size_box.pack(padx=15,anchor="w")

        ttk.Label(w,text="Nº Rigs:").pack(anchor="w",padx=15,pady=(10,2))
        rigs_var=tk.StringVar(value=str((existing or {}).get("rigs", 1)) if existing else "1")
        rigs_box=ttk.Combobox(w,textvariable=rigs_var,values=["1","2","3","4","5","6"],state="readonly",width=8)
        rigs_box.pack(padx=15,anchor="w")

        result=[None]
        def ok():
            result[0]=(name_var.get().strip(),size_var.get(),int(rigs_var.get()))
            w.destroy()
        def cancel():
            w.destroy()
        buttons=ttk.Frame(w);buttons.pack(pady=12)
        ttk.Button(buttons,text="OK",command=ok).pack(side="left",padx=5)
        ttk.Button(buttons,text="Cancelar",command=cancel).pack(side="left",padx=5)
        w.protocol("WM_DELETE_WINDOW",cancel)
        ent.focus()
        w.wait_window()
        return result[0]

    # Apresenta o menu contextual de um depósito ou rig.
    def right_click(self,e,best=None):
        if self.center_lat is None:
            return
        if best is None:
            best=self._marker_at(e)
        if best is None:
            return
        kind,i=best
        menu=tk.Menu(self.root,tearoff=False)
        if kind=="deposit":
            d=self.deposits[i]
            menu.add_command(label=f"Depósito: {d.get('name','Depósito')}",state="disabled")
            menu.add_separator()
            menu.add_command(label="Copiar coordenadas",command=lambda:self.copy_coords(d))
            menu.add_command(label="Editar depósito",command=lambda:self.edit_deposit(i))
            menu.add_command(label="Apagar depósito",command=lambda:self.delete_deposit(i))
        else:
            menu.add_command(label="Rig",state="disabled")
            menu.add_separator()
            menu.add_command(label="Apagar rig",command=lambda:self.delete_rig(i))
        menu.add_separator()
        menu.add_command(label="Cancelar")
        menu.tk_popup(e.x_root,e.y_root)
        menu.grab_release()

    # Copia as coordenadas de um depósito para o clipboard do Windows.
    def copy_coords(self,d):
        text=f"{float(d['lat']):.5f} {float(d['lon']):.5f}"
        self.root.clipboard_clear();self.root.clipboard_append(text);self.root.update()
        self.info.set(f"Coordenadas copiadas: {text}")

    # Edita um depósito já existente.
    def edit_deposit(self,i):
        d=self.deposits[i]
        result=self.deposit_editor(self.root, d.get("lat"), d.get("lon"), d)
        if result is None:
            return
        name,size,nrigs=result
        d["name"]=name or "Depósito"
        d["size"]=size
        d["rigs"]=nrigs
        self.draw()

    # Apaga um depósito depois de pedir confirmação.
    def delete_deposit(self,i):
        d=self.deposits[i]
        if messagebox.askyesno("Apagar depósito",f"Apagar o depósito «{d.get('name','Depósito')}»?"):
            del self.deposits[i]
            self.draw()

    # Apaga um rig depois de pedir confirmação.
    def delete_rig(self,i):
        if messagebox.askyesno("Apagar rig","Apagar este rig?"):
            del self.rigs[i]
            self.draw()

    # Calcula o destino PRÓXIMO da procura.
    # Na Fase 3, os destinos formam uma circunferência de 3,5 km em torno
    # do Datum, com espaçamento alvo de 1,8 km e avanço no sentido horário.
    def update_next(self):
        if self.search_started and self.datum_lat is not None and self.datum_lon is not None:
            # -----------------------------------------------------------------
            # Estratégia da Fase 3
            # - raio da circunferência: 3.500 m
            # - espaçamento máximo pretendido: 1.800 m
            # - primeiro destino: Norte (000°)
            # - sentido: horário
            # O número de pontos é calculado automaticamente para que o
            # espaçamento entre destinos não ultrapasse o valor pretendido.
            # -----------------------------------------------------------------
            # Fase 3: percurso circular com raio de 3,5 km e espaçamento alvo de 1,8 km.
            datum_x, datum_y = self.llxy(self.datum_lat, self.datum_lon)
            radius = 3500.0
            spacing = 1800.0
            total_points = max(1, math.ceil((2.0 * math.pi * radius) / spacing))
            if self.route_index >= total_points:
                self.next_target_xy = None
                self.nextinfo.set("Sec. Sugerido: Procura circular concluída")
                return
            step_angle = (2.0 * math.pi) / total_points
            # O primeiro ponto é a norte; os seguintes avançam no sentido horário.
            angle = self.route_index * step_angle
            target_x = datum_x + radius * math.sin(angle)
            target_y = datum_y + radius * math.cos(angle)
            self.next_target_xy = (target_x, target_y)
            lat, lon = self.xyll(target_x, target_y)

            if self.rhino_lat is not None and self.rhino_lon is not None:
                rx, ry = self.llxy(self.rhino_lat, self.rhino_lon)
                dist = math.hypot(target_x-rx, target_y-ry)
                if dist <= 100.0:
                    # Regista o destino antes de avançar para o seguinte.
                    self.route_history.append({
                        "number": self.route_index + 1,
                        "x": target_x,
                        "y": target_y,
                        "status": "reached"
                    })
                    # Ao alcançar o último ponto, a volta fica concluída.
                    if self.route_index >= total_points - 1:
                        self.route_index = total_points
                        self.next_target_xy = None
                        self.nextinfo.set("Sec. Sugerido: Procura circular concluída")
                        return
                    self.route_index += 1
                    angle = self.route_index * step_angle
                    target_x = datum_x + radius * math.sin(angle)
                    target_y = datum_y + radius * math.cos(angle)
                    self.next_target_xy = (target_x, target_y)
                    lat, lon = self.xyll(target_x, target_y)
                    dist = math.hypot(target_x-rx, target_y-ry)

                bearing = (math.degrees(math.atan2(target_x-rx, target_y-ry)) + 360.0) % 360.0
                self.nextinfo.set(f"Sec. Sugerido: Rumo {bearing:03.0f}° | Distância {dist/1000:.2f} km | {lat:.5f}°, {lon:.5f}°")
                return

            self.nextinfo.set(f"Sec. Sugerido: Rumo 000° | Distância 3,50 km | {lat:.5f}°, {lon:.5f}°")
            return

        if not self.points:
            self.next_target_xy = None
            self.nextinfo.set("Sec. Sugerido: —");return
        p=max(self.points,key=lambda q:q["y"])
        x=p["x"];y=p["y"]+self.width.get()*0.85
        lat,lon=self.xyll(x,y)
        self.nextinfo.set(f"Sec. Sugerido: {lat:.5f}°, {lon:.5f}°")

    # Guarda o estado completo do mapa num ficheiro JSON.
    def save(self):
        if self.center_lat is None:return
        p=filedialog.asksaveasfilename(defaultextension=".json",filetypes=[("Rhino Map","*.json")])
        if not p:return
        # Tudo o que é necessário para reconstruir a sessão é guardado:
        # planeta, parâmetros do mapa, estado da busca, Datum, índice do
        # destino atual e todos os marcadores/pontos recolhidos.
        data={"system":self.system,"body":self.body,"center_lat":self.center_lat,"center_lon":self.center_lon,
              "planet_radius":self.radius,"coverage_width_m":self.width.get(),"scanner_range_m":self.scanner.get(),
              "search_started":self.search_started,"datum_lat":self.datum_lat,"datum_lon":self.datum_lon,
              "route_index":self.route_index,
              "route_history":self.route_history,
              "points":self.points,"deposits":self.deposits,"rigs":self.rigs}
        Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

    # Carrega um mapa previamente guardado e repõe o seu estado.
    def load(self):
        p=filedialog.askopenfilename(filetypes=[("Rhino Map","*.json")])
        if not p:return
        try:
            d=json.loads(Path(p).read_text(encoding="utf-8"))
            self.system=d.get("system","");self.body=d.get("body","");self.body_key=f"{self.system}|{self.body}"
            self.center_lat=float(d["center_lat"]);self.center_lon=float(d["center_lon"])
            self.radius=float(d.get("planet_radius",6371000));self.width.set(float(d.get("coverage_width_m",500)))
            self.scanner.set(float(d.get("scanner_range_m",2000)))
            self.search_started=bool(d.get("search_started",False))
            self.datum_lat=d.get("datum_lat")
            self.datum_lon=d.get("datum_lon")
            if self.datum_lat is not None:self.datum_lat=float(self.datum_lat)
            if self.datum_lon is not None:self.datum_lon=float(self.datum_lon)
            self.route_index=int(d.get("route_index",0))
            self.route_history=d.get("route_history",[])
            self.points=d.get("points",[]);self.deposits=d.get("deposits",[]);self.rigs=d.get("rigs",[])
            for dep in self.deposits:
                dep.setdefault("size","Pequeno")
                dep.setdefault("rigs",1)
            self.last_xy=(self.points[-1]["x"],self.points[-1]["y"]) if self.points else None
            self.zoom=1.0; self.view_center=None; self.view_user_controlled=False; self.base_scale=None
            self.draw();self.update_next();self.update_overlay()
        except Exception as e:messagebox.showerror("Erro",str(e))

if __name__=="__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    root=tk.Tk();App(root);root.mainloop()
