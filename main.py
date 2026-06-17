import config as cfg_module
from fetcher import UsageFetcher
from overlay import Overlay
from tray import TrayIcon


def main():
    config = cfg_module.load()
    fetcher = UsageFetcher(config)
    overlay = Overlay(fetcher, config)   # starts hidden unless overlay_visible
    tray = TrayIcon(fetcher, config, overlay)
    overlay.on_quit = tray.icon.stop     # overlay's own Quit also removes the tray icon
    tray.start()
    overlay.run()


if __name__ == "__main__":
    main()
