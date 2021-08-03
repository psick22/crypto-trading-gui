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

    binance = BinanceFuturesClient('', '', True)
    root = Root(binance)

    root.mainloop()
