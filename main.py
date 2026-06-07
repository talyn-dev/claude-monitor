import config as cfg_module
from fetcher import UsageFetcher
from overlay import Overlay


def main():
    config = cfg_module.load()
    fetcher = UsageFetcher(config)
    overlay = Overlay(fetcher, config)
    overlay.run()


if __name__ == "__main__":
    main()
