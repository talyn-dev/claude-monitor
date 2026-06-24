import argparse

import config as cfg_module
from fetcher import UsageFetcher
from overlay import Overlay
from tray import TrayIcon


def main():
    parser = argparse.ArgumentParser(description="Claude usage overlay")
    parser.add_argument("--config", metavar="PATH",
                        help="path to a config.json (run multiple instances, one per account)")
    args = parser.parse_args()

    config = cfg_module.load(args.config)
    fetcher = UsageFetcher(config)
    overlay = Overlay(fetcher, config)   # starts hidden unless overlay_visible
    tray = TrayIcon(fetcher, config, overlay)
    overlay.on_quit = tray.icon.stop     # overlay's own Quit also removes the tray icon
    tray.start()
    overlay.run()


if __name__ == "__main__":
    main()
