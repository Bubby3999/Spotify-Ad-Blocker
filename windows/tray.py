"""Windows notification icon; callbacks are dispatched to the Tk event queue."""

import threading


class TrayIcon:
    def __init__(self, dispatch):
        import pystray
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (30, 30, 30, 255))
        drawing = ImageDraw.Draw(image)
        drawing.line([(27, 43), (27, 17), (48, 12), (48, 38)], fill="white", width=5)
        drawing.ellipse((15, 38, 29, 50), fill="white")
        drawing.ellipse((36, 33, 50, 45), fill="white")
        menu = pystray.Menu(
            pystray.MenuItem("Spotify Control Dashboard", lambda icon, item: dispatch("show"), default=True),
            pystray.MenuItem("Instructions", lambda icon, item: dispatch("instructions")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit helper", lambda icon, item: dispatch("quit")),
        )
        self.icon = pystray.Icon("spotify-control", image, "Spotify Control", menu)

    def start(self):
        ready = threading.Event()
        errors = []
        def setup(icon):
            try:
                icon.visible = True
            except Exception as error:
                errors.append(error)
            finally:
                ready.set()
        self.icon.run_detached(setup)
        if not ready.wait(3) or errors:
            self.icon.stop()
            raise RuntimeError("The system tray icon could not be displayed")

    def stop(self):
        self.icon.stop()
