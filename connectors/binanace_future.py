import logging
from urllib.parse import urlencode
from typing import List, Dict, Union
import requests
import pprint
import websocket
import threading
import json
import time

import hmac
import hashlib

from models import Balance, Candle, Contract, OrderStatus
from strategies import BreakoutStrategy, TechnicalStrategy

logger = logging.getLogger()


class BinanceFuturesClient:
    def __init__(self, public_key: str, secret_key: str, testnet: bool):

        self.logs = []

        if testnet:
            self._base_url = "https://testnet.binancefuture.com"
            self._wss_url = "wss://stream.binancefuture.com/ws"
        else:
            self._base_url = "http://fapi.binance.com"
            self._wss_url = "wss://fstream.binance.com/ws"

        self._public_key = public_key
        self._secret_key = secret_key

        self.headers = {
            'X-MBX-APIKEY': self._public_key
        }

        self.contracts = self.get_contracts()
        self.balances = self.get_balances()

        self.prices = dict()
        self._ws_id = 1
        self._ws = None
        self.strategies: Dict[int, Union[TechnicalStrategy, BreakoutStrategy]] = {}

        t = threading.Thread(target=self._start_ws)
        # t.start()

        logger.info("Binance Futures Client successfully initialized")

    def _add_log(self, msg: str):
        logger.info(msg)
        self.logs.append({"log": msg, "displayed": False})

    def _generated_signature(self, data: Dict) -> str:

        return hmac.new(self._secret_key.encode(), urlencode(data).encode(), hashlib.sha256).hexdigest()

    def _make_request(self, method: str, endpoint: str, data: Dict):
        if method == 'GET':
            try:
                response = requests.get(self._base_url + endpoint, params=data, headers=self.headers)
            except Exception as e:
                logger.error(f"Connection error while making {method} request to {endpoint}: {e}")
                return None

        elif method == 'POST':
            try:
                response = requests.post(self._base_url + endpoint, params=data, headers=self.headers)
            except Exception as e:
                logger.error(f"Connection error while making {method} request to {endpoint}: {e}")
                return None

        elif method == 'DELETE':
            try:
                response = requests.delete(self._base_url + endpoint, params=data, headers=self.headers)
            except Exception as e:
                logger.error(f"Connection error while making {method} request to {endpoint}: {e}")
                return None

        else:
            raise ValueError()

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                f"Error while making {method} request to {endpoint} : ({response.status_code}) {response.json()}")
            return None

    def get_contracts(self) -> Dict[str, Contract]:
        exchange_info = self._make_request("GET", "/fapi/v1/exchangeInfo", {})

        contracts = dict()

        if exchange_info is not None:
            for contract in exchange_info['symbols']:
                contracts[contract['symbol']] = Contract(contract, "binance")

        return contracts

    def get_historical_candles(self, contract: Contract, interval: str) -> List[Candle]:
        data = dict()
        data['symbol'] = contract.symbol
        data['interval'] = interval
        data['limit'] = 1000

        raw_candles = self._make_request('GET', '/fapi/v1/klines', data)

        candles = []
        if raw_candles is not None:
            for candle in raw_candles:
                candles.append(Candle(candle, interval, "binance"))

        return candles

    def get_bid_ask(self, contract: Contract) -> Dict[str, float]:
        data = dict()
        data['symbol'] = contract.symbol
        order_book_data = self._make_request("GET", "/fapi/v1/ticker/bookTicker", data)
        if order_book_data is not None:
            if contract.symbol not in self.prices:
                self.prices[contract.symbol] = {
                    'bid': float(order_book_data['bidPrice']),
                    'ask': float(order_book_data['askPrice'])
                }
            else:
                self.prices[contract.symbol]['bid'] = float(order_book_data['bidPrice'])
                self.prices[contract.symbol]['ask'] = float(order_book_data['askPrice'])

            return self.prices[contract.symbol]

    def get_balances(self) -> Dict[str, Balance]:
        data = dict()
        data['timestamp'] = int(time.time() * 1000)
        data['signature'] = self._generated_signature(data)
        balances = dict()
        account_data = self._make_request('GET', '/fapi/v1/account', data)
        if account_data is not None:
            for a in account_data['assets']:
                balances[a['asset']] = Balance(a)

        return balances

    def place_order(self, contract: Contract, order_type: str, quantity: float, side: str, price=None,
                    tif=None) -> OrderStatus:
        data = dict()
        data['symbol'] = contract.symbol
        data['side'] = side.upper()
        data['quantity'] = round(round(quantity / contract.lot_size) * contract.lot_size, 8)
        data['type'] = order_type

        if price is not None:
            data['price'] = round(round(price / contract.tick_size) * contract.tick_size, 8)

        if tif is not None:
            data['timeInForce'] = tif

        data['timestamp'] = int(time.time() * 1000)
        data['signature'] = self._generated_signature(data)

        order_status = self._make_request("POST", '/fapi/v1/order', data)

        if order_status is not None:
            order_status = OrderStatus(order_status)

        return order_status

    def cancel_order(self, contract: Contract, order_id: str) -> OrderStatus:
        data = dict()
        data['symbol'] = contract.symbol
        data['order_id'] = order_id
        data['timestamp'] = int(time.time() * 1000)
        data['signature'] = self._generated_signature(data)
        order_status = self._make_request("DELETE", '/fapi/v1/order', data)

        if order_status is not None:
            order_status = OrderStatus(order_status)

        return order_status

    def get_order_status(self, contract: Contract, order_id: int) -> OrderStatus:
        data = dict()
        data['timestamp'] = int(time.time() * 1000)
        data['symbol'] = contract.symbol
        data['order_id'] = order_id
        data['signature'] = self._generated_signature(data)

        order_status = self._make_request('GET', '/fapi/v1/order', data)
        if order_status is not None:
            order_status = OrderStatus(order_status)

        return order_status

    def _start_ws(self):
        self.ws = websocket.WebSocketApp(self._wss_url, on_open=self._on_open, on_close=self._on_close,
                                         on_error=self._on_error,
                                         on_message=self._on_message)

        while True:
            try:
                self.ws.run_forever()
            except Exception as e:
                logger.error(f"Binance error in run_forever() method : {e}")
                time.sleep(2)

    def _on_open(self, ws):
        logger.info("websocket opened")
        self.subscribe_channel(list(self.contracts.values()), "bookTicker")
        self.subscribe_channel(list(self.contracts.values()), "aggTrade")

    def _on_close(self, ws):
        logger.warning("websocket closed")

    def _on_error(self, ws, msg: str):
        logger.error("websocket error", msg)

    def _on_message(self, ws, msg: str):

        data = json.loads(msg)
        if "e" in data:
            if data["e"] == 'bookTicker':
                symbol = data["s"]
                if symbol not in self.prices:
                    self.prices[symbol] = {'bid': float(data['b']), 'ask': float(data['a'])}
                else:
                    self.prices[symbol]['bid'] = float(data['b'])
                    self.prices[symbol]['ask'] = float(data['a'])

                # pnl 계산
                try:
                    for b_index, strat in self.strategies.items():
                        if strat.contract.symbol == symbol:
                            for trade in strat.trades:
                                if trade.status == "open" and trade.entry_price is not None:
                                    if trade.side == "long":
                                        trade_pnl = (self.prices[symbol]['bid'] - trade.entry_price) * trade.quantity
                                    elif trade.side == "short":
                                        trade_pnl = (trade.entry_price - self.prices[symbol]['ask']) * trade.quantity
                except RuntimeError as e:
                    logger.error("error while lopping through the binance strategies : ", e)


            elif data["e"] == 'aggTrade':
                symbol = data['s']

                # 웹소켓 거래 데이터가 들어올때마다 등록된 전략을 실행
                for key, strat in self.strategies.items():
                    if strat.contract.symbol == symbol:
                        res = strat.parse_trades(float(data['p']), float(data['q']), data['T'])
                        strat.check_trade(res)

    def subscribe_channel(self, contracts: List[Contract], channel: str):
        data = dict()
        data['method'] = "SUBSCRIBE"
        data['params'] = []

        for contract in contracts:
            data['params'].append(contract.symbol.lower() + "@" + channel)
        data['id'] = self._ws_id
        try:
            self.ws.send(json.dumps(data))
        except Exception as e:
            logger.error(f"Connection error while subscribing to {len(contracts)} {channel} updates: {e}")

        self._ws_id += 1

    def get_trade_size(self, contract: Contract, price: float, balance_pct: float):
        balance = self.get_balances()
        if balance is not None:
            if 'USDT' in balance:
                balance = balance['USDT'].wallet_balance
            else:
                return None
        else:
            return None

        trade_size = (balance * balance_pct / 100) / price

        trade_size = round(round(trade_size / contract.lot_size) * contract.lot_size, 8)
        logger.info(f"Binance Futures current USDT balance={balance}, trade size={trade_size}")

        return trade_size
