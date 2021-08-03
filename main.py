import tkinter as tk
import logging

from connectors.binanace_future import BinanceFuturesClient
from interface.root_component import Root

logger = logging.getLogger()
logger.debug("debug mode")
logger.info("basic information")
logger.warning("warning")
logger.error("error")

logger.setLevel(logging.INFO)

stream_handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s [%(levelname)s] | %(message)s')
stream_handler.setFormatter(formatter)
stream_handler.setLevel(logging.INFO)

file_handler = logging.FileHandler("info.log")
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)

logger.addHandler(stream_handler)
logger.addHandler(file_handler)

if __name__ == '__main__':
    binance = BinanceFuturesClient('b57c459c43af304beeb357b5b5eab7b607aead0a0af805428dbedae79a496331',
                                   'dc75f5048016ca45c7812856bc6433e4665ef9c87f99882bb5f48a2fc4508ce8', True)
    root = Root(binance)

    root.mainloop()
