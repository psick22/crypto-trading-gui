import logging
import time
from typing import Dict, List, Tuple, TYPE_CHECKING
import pandas as pd
from threading import Timer

from models import Contract, Candle, Trade

if TYPE_CHECKING:
    from connectors.binanace_future import BinanceFuturesClient

logger = logging.getLogger()

TF_EQUIV = {"1m": 50, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}


class Strategy:
    def __init__(self, client: "BinanceFuturesClient", contract: Contract, exchange: str, timeframe: str,
                 balance_pct: float,
                 take_profit: float,
                 stop_loss: float,
                 strat_name: str):
        self.client = client
        self.contract = contract
        self.exchange = exchange
        self.tf = timeframe
        self.tf_equiv = TF_EQUIV[timeframe] * 1000
        self.balance_pct = balance_pct
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.strat_name = strat_name
        self.ongoing_position = False

        self.candles: List[Candle] = []
        self.trades: List[Trade] = []
        self.logs = []

    def _add_log(self, msg: str):
        logger.info(msg)
        self.logs.append({"log": msg, "displayed": False})

    def parse_trades(self, price: float, size: float, timestamp: int) -> str:

        """
        - 새로운 거래의 timestamap 비교를 통한 세가지 경우의 수
        1) 같은 캔들일 경우 ->현재 캔들을 업데이트
        2) 새로운 캔들의 첫번째 거래일 경우 -> 새로운 캔들을 생성
        3) 새로운 캔들의 첫번째 거래이지만 마지막 캔들과 현재 캔들사이의 누락이 발생했을 때 (거래가 없었던 경우)
        """

        timestamp_diff = int(time.time() * 1000) - timestamp
        if timestamp_diff >= 2000:
            logger.warning(
                f"{self.exchange} {self.contract.symbol} : {timestamp_diff} ms of difference between the current time and the trade time")

        last_candle = self.candles[-1]

        # 1) 같은 캔들인 경우
        if timestamp < last_candle.timestamp + self.tf_equiv:
            last_candle.close = price
            last_candle.volume += size

            if price > last_candle.high:
                last_candle.high = price
            elif price < last_candle.low:
                last_candle.low = price

            return "some_candle"


        # 3) 누락된 캔들이 있을 경우
        elif timestamp >= last_candle.timestamp + 2 * self.tf_equiv:
            missing_candles = int((timestamp - last_candle.timestamp) / self.tf_equiv) - 1

            logger.info(
                f"{self.exchange} missing {missing_candles} candles for {self.contract.symbol} {self.tf} ({timestamp} {last_candle.timestamp})")

            for missing in range(missing_candles):
                new_ts = last_candle.timestamp + self.tf_equiv
                candle_info = {
                    'ts': new_ts,
                    'open': last_candle.close,
                    'high': last_candle.close,
                    'close': last_candle.close,
                    'low': last_candle.close,
                    'volume': 0,
                }
                new_candle = Candle(candle_info, self.tf, "parse_trade")
                self.candles.append(new_candle)
                last_candle = new_candle

            new_ts = last_candle.timestamp + self.tf_equiv
            candle_info = {
                'ts': new_ts,
                'open': last_candle.close,
                'high': last_candle.close,
                'close': last_candle.close,
                'low': last_candle.close,
                'volume': 0,
            }
            new_candle = Candle(candle_info, self.tf, "parse_trade")
            self.candles.append(new_candle)

            return "new_candle"



        # 2) 새로운 캔들일 경우
        elif timestamp >= last_candle.timestamp + self.tf_equiv:
            new_ts = last_candle.timestamp + self.tf_equiv
            candle_info = {
                'ts': new_ts,
                'open': price,
                'high': price,
                'close': price,
                'low': price,
                'volume': size,
            }
            new_candle = Candle(candle_info, self.tf, "parse_trade")
            self.candles.append(new_candle)

            logger.info(f"{self.exchange} New candle for {self.contract.symbol} {self.tf}")

            return "new_candle"

    def _check_order_status(self, order_id):
        order_status = self.client.get_order_status(self.contract, order_id)
        if order_status is not None:
            logger.info(f"{self.exchange} order status : {order_status.status}")

            if order_status.status == 'filled':
                for trade in self.trades:
                    if trade.entry_id == order_id:
                        trade.entry_price = order_status.avg_price
                        break
                return

        # order_status.status 가 filled 상태가 될떄까지 2초마다 반복
        t = Timer(2.0, lambda: self._check_order_status(order_id))
        t.start()

    def _open_position(self, signal_result: int):
        trade_size = self.client.get_trade_size(self.contract, self.candles[-1].close, self.balance_pct)
        if trade_size is None:
            return None

        order_side = "buy" if signal_result == 1 else "sell"
        position_side = "long" if signal_result == 1 else "short"

        self._add_log(f"{position_side} signal on {self.contract.symbol} {self.tf}")
        order_status = self.client.place_order(self.contract, "MARKET", trade_size, order_side)

        if order_status is not None:
            self._add_log(f"{order_side.capitalize()} order placed on {self.exchange} | Status : {order_status.status}")
            self.ongoing_position = True

            avg_fill_price = None

            if order_status.status == 'filled':
                avg_fill_price = order_status.avg_price
            else:
                t = Timer(2.0, lambda: self._check_order_status(order_status.order_id))
                t.start()

            new_trade = Trade(
                {"time": int(time.time() * 1000), "entry_price": avg_fill_price, "contract": self.contract,
                 "strategy": self.strat_name, "side": position_side, "status": "open", "pnl": 0, "quantity": trade_size,
                 "entry_id": order_status.order_id})

            self.trades.append(new_trade)


class TechnicalStrategy(Strategy):
    def __init__(self, client, contract: Contract, exchange: str, timeframe: str, balance_pct: float,
                 take_profit: float,
                 stop_loss: float, other_params: Dict):
        super().__init__(client, contract, exchange, timeframe, balance_pct, take_profit, stop_loss, "Technical")

        self._ema_fast = other_params['ema_fast']
        self._ema_slow = other_params['ema_slow']
        self._ema_signal = other_params['ema_signal']

        self._rsi_length = other_params['rsi_length']

    def _rsi(self):
        close_list = []
        for candle in self.candles:
            close_list.append(candle.close)

        closes = pd.Series(close_list)

        delta = closes.diff().dropna()

        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0
        down[down > 0] = 0
        avg_gain = up.ewm(com=(self._rsi_length - 1), min_periods=self._rsi_length).mean()
        avg_loss = down.abs().ewm(com=(self._rsi_length - 1), min_periods=self._rsi_length).mean()

        rs = avg_gain / avg_loss

        rsi = 100 - 100 / (1 + rs)
        rsi = rsi.round(2)

        return rsi.iloc[-2]

    def _macd(self) -> Tuple[float, float]:
        """
        1) Fast EMA 계산
        2) Slow EMA 계산
        3) Fast EMA - Slow EMA
        4) 3의 결과의 EMA

        """
        close_list = []
        for candle in self.candles:
            close_list.append(candle.close)

        closes = pd.Series(close_list)
        ema_fast = closes.ewm(span=self._ema_fast).mean()
        ema_slow = closes.ewm(span=self._ema_slow).mean()

        macd_line = ema_fast - ema_slow
        macd_signal = macd_line.ewm(span=self._ema_signal).mean()

        return macd_line.iloc[-2], macd_signal.iloc[-2]

    def _check_signal(self):
        """
        이 메서드를 on_message 에서 live data update가 있을 때 마다 호출할지 ?
        또는, 캔들이 하나가 완성될 때마다?
        """

        macd_line, macd_signal = self._macd()
        rsi = self._rsi()

        print(rsi, macd_line, macd_signal)

        if rsi < 30 and macd_line > macd_signal:
            return 1
        elif rsi > 70 and macd_line < macd_signal:
            return -1
        else:
            return 0

    def check_trade(self, tick_type: str):
        if tick_type == "new_candle" and not self.ongoing_position:
            signal_result = self._check_signal()

            if signal_result in [-1, 1]:
                self._open_position(signal_result)


class BreakoutStrategy(Strategy):
    def __init__(self, client, contract: Contract, exchange: str, timeframe: str, balance_pct: float,
                 take_profit: float,
                 stop_loss: float, other_params: Dict):
        super().__init__(client, contract, exchange, timeframe, balance_pct, take_profit, stop_loss, "Breakout")

        self._min_volume = other_params['min_volume']

    def _check_signal(self) -> int:
        if self.candles[-1].close > self.candles[-2].high and self.candles[-1].volume > self._min_volume:
            return 1
        elif self.candles[-1].close < self.candles[-2].low and self.candles[-1].volume > self._min_volume:
            return -1
        else:
            return 0

        # # inside bar 패턴 (https://backtest-rookies.com/2018/07/13/tradingview-inside-bar-momentum-strategy/)
        # if self.candles[-2].high < self.candles[-3].high and self.candles[-2].low > self.candles[-3].low:
        #     if self.candles[-1].close > self.candles[-3].high:
        #         # 상방 돌파
        #         pass
        #     elif self.candles[-1].close < self.candles[3].low:
        #         # 하방 돌파
        #         pass

    def check_trade(self, tick_type: str):
        if not self.ongoing_position:
            signal_result = self._check_signal()

            if signal_result in [- 1, 1]:
                self._open_position(signal_result)
