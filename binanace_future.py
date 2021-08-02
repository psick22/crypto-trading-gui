import logging
import requests
import pprint
import websocket
import threading

logger = logging.getLogger()


class BinanceFuturesClient:
    def __init__(self, testnet):
        if testnet:
            self.base_url = "https://testnet.binancefuture.com"
            self.wss_url = "wss://stream.binancefuture.com/ws"
        else:
            self.base_url = "http://fapi.binance.com"
            self.wss_url = "wss://fstream.binance.com/ws"

        t = threading.Thread(target=self.start_ws)
        t.start()

        logger.info("Binance Futures Client successfully initialized")

    def make_request(self, method, endpoint, data):
        if method == 'GET':
            response = requests.get(self.base_url + endpoint, params=data)
        else:
            raise ValueError()

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                f"Error while making {method} request to {endpoint} : ({response.status_code}) {response.json()}")
            return None

    def get_contracts(self):
        exchange_info = self.make_request("GET", "/fapi/v1/exchangeInfo", None)

        contracts = dict()

        if exchange_info is not None:
            for contract in exchange_info['symbols']:
                contracts[contract['pair']] = contract

        return contracts

    def get_historical_candles(self):
        return

    def get_bid_ask(self):
        return

    def start_ws(self):
        ws = websocket.WebSocketApp(self.wss_url, on_open=self.on_open, on_close=self.on_close, on_error=self.on_error,
                                    on_message=self.on_message)
        ws.run_forever()
        return

    def on_open(self, ws):
        logger.info("websocket opened")

    def on_close(self, ws):
        logger.warning("websocket closed")

    def on_error(self, ws, msg):
        logger.error("websocket error", msg)

    def on_message(self, ws, msg):
        print(msg)
