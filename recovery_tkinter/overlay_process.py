"""Overlay isolado: Tkinter e Qt nunca partilham o ciclo de eventos."""
import multiprocessing


def run_overlay(connection):
    # Imports apenas no processo filho, incluindo QApplication.
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        if __package__:
            from .pyqt_overlay import OverlayWindow
        else:
            from pyqt_overlay import OverlayWindow
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        window = OverlayWindow()
        screen = app.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            window.move(area.x() + (area.width() - window.width()) // 2, area.y() + 40)
        window.show()
        connection.send(('ready', None))

        def receive():
            try:
                while connection.poll():
                    command, payload = connection.recv()
                    if command == 'close':
                        window.close()
                        app.quit()
                        return
                    if command == 'navigation':
                        window.set_navigation(*payload)
                    elif command == 'show':
                        window.show()
                        window.raise_()
                    elif command == 'hide':
                        window.hide()
            except (EOFError, OSError):
                app.quit()

        timer = QTimer()
        timer.timeout.connect(receive)
        timer.start(20)
        app.exec()
    except Exception as exc:
        try:
            connection.send(('error', str(exc)))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class OverlayProcess:
    def __init__(self):
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=run_overlay, args=(child,), daemon=True)
        self.visible = True
        self.process.start()
        child.close()
        try:
            if not self.connection.poll(10):
                raise RuntimeError('O overlay não respondeu ao arranque.')
            result, detail = self.connection.recv()
            if result != 'ready':
                raise RuntimeError(detail)
        except Exception:
            self.close()
            raise

    def _send(self, command, payload=None):
        if not self.process.is_alive():
            raise RuntimeError('O processo do overlay terminou.')
        self.connection.send((command, payload))

    def set_navigation(self, *values):
        self._send('navigation', values)

    def show(self):
        self._send('show')
        self.visible = True

    def hide(self):
        self._send('hide')
        self.visible = False

    def isVisible(self):
        return self.visible and self.process.is_alive()

    def raise_(self):
        pass  # show já coloca a janela no topo.

    def close(self):
        if self.process.is_alive():
            try:
                self._send('close')
            except (OSError, EOFError):
                pass
            self.process.join(2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(2)
        self.connection.close()
        self.visible = False
