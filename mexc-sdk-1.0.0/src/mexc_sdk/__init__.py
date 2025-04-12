'''
# mexc-api-sdk

MEXC Official Market and trade api sdk, easy to connection and send request to MEXC open api !

## Table of APIS

* [Init](#init)
* [Market](#market)

  * [Ping](#ping)
  * [Check Server Time](#check-server-time)
  * [Exchange Information](#exchange-information)
  * [Recent Trades List](#recent-trades-list)
  * [Order Book](#order-book)
  * [Old Trade Lookup](#old-trade-lookup)
  * [Aggregate Trades List](#aggregate-trades-list)
  * [kline Data](#kline-data)
  * [Current Average Price](#current-average-price)
  * [24hr Ticker Price Change Statistics](#24hr-ticker-price-change-statistics)
  * [Symbol Price Ticker](#symbol-price-ticker)
  * [Symbol Order Book Ticker](#symbol-order-book-ticker)
* [Trade](#trade)

  * [Test New Order](#test-new-order)
  * [New Order](#new-order)
  * [cancel-order](#cancel-order)
  * [Cancel all Open Orders on a Symbol](#cancel-all-open-orders-on-a-symbol)
  * [Query Order](#query-order)
  * [Current Open Orders](#current-open-orders)
  * [All Orders](#all-orders)
  * [Account Information](#account-information)
  * [Account Trade List](#account-trade-list)

## Init

```javascript
//Javascript
import * as Mexc from 'mexc-sdk';
const apiKey = 'apiKey'
const apiSecret = 'apiSecret'
const client = new Mexc.Spot(apiKey, apiSecret);
```

```go
// Go
package main
import (
	"fmt"
	"mexc-sdk/mexcsdk"
)

func main() {
	apiKey := "apiKey"
	apiSecret := "apiSecret"
	spot := mexcsdk.NewSpot(apiKey, apiSecret)
}
```

```python
# python
from mexc_sdk import Spot
spot = Spot(api_key='apiKey', apiSecret='apiSecret')
```

```java
// java
import Mexc.Sdk.*;
class MyClass {
  public static void main(String[] args) {
    String apiKey= "apiKey";
    String apiSecret= "apiSecret";
    Spot mySpot = new Spot(apiKey, apiSecret);
  }
}
```

```C#
// dotnet
using System;
using System.Collections.Generic;
using Mxc.Sdk;

namespace dotnet
{
    class Program
    {
        static void Main(string[] args)
        {
            string  apiKey = "apiKey";
            string  apiSecret= "apiSecret";
            var spot = new Spot(apiKey, apiSecret);
        }
    }
}

```

## Market

### Ping

```javascript
client.ping()
```

### Check Server Time

```javascript
client.time()
```

### Exchange Information

```javascript
client.exchangeInfo(options: any)
options:{symbol, symbols}
/**
 * choose one parameter
 *
 * symbol :
 *      example "BNBBTC";
 *
 * symbols :
 *      array of symbol
 *      example ["BTCUSDT","BNBBTC"];
 *
 */
```

### Recent Trades List

```javascript
client.trades(symbol: string, options: any = { limit: 500 })
options:{limit}
/**
 *
 * limit :
 *      Number of returned data
 *      Default 500;
 *      max 1000;
 *
 */
```

### Order Book

```javascript
client.depth(symbol: string, options: any = { limit: 100 })
options:{limit}
/**
 * limit :
 *      Number of returned data
 *      Default 100;
 *      max 5000;
 *      Valid:[5, 10, 20, 50, 100, 500, 1000, 5000]
 *
 */
```

### Old Trade Lookup

```javascript
client.historicalTrades(symbol: string, options: any = { limit: 500 })
options:{limit, fromId}
/**
 *
 * limit :
 *      Number of returned data
 *      Default 500;
 *      max 1000;
 *
 * fromId:
 *      Trade id to fetch from. Default gets most recent trades
 *
 */

```

### Aggregate Trades List

```javascript
client.aggTrades(symbol: string, options: any = { limit: 500 })
options:{fromId, startTime, endTime, limit}
/**
 *
 * fromId :
 *      id to get aggregate trades from INCLUSIVE
 *
 * startTime:
 *      start at
 *
 * endTime:
 *      end at
 *
 * limit :
 *      Number of returned data
 *      Default 500;
 *      max 1000;
 *
 */
```

### kline Data

```javascript
client.klines(symbol: string, interval: string, options: any = { limit: 500 })
options:{ startTime, endTime, limit}
/**
 *
 * interval :
 *      m :minute;
 *      h :Hour;
 *      d :day;
 *      w :week;
 *      M :month
 *      example : "1m"
 *
 * startTime :
 *      start at
 *
 * endTime :
 *      end at
 *
 * limit :
 *      Number of returned data
 *      Default 500;
 *      max 1000;
 *
 */
```

### Current Average Price

```javascript
client.avgPrice(symbol: string)
```

### 24hr Ticker Price Change Statistics

```javascript
client.ticker24hr(symbol?: string)
```

### Symbol Price Ticker

```javascript
client.tickerPrice(symbol?: string)
```

### Symbol Order Book Ticker

```javascript
client.bookTicker(symbol?: string)
```

## Trade

### Test New Order

```javascript
client.newOrderTest(symbol: string, side: string, orderType: string, options: any = {})
options:{ timeInForce, quantity, quoteOrderQty, price, newClientOrderId, stopPrice, icebergQty, newOrderRespType, recvWindow}
/**
 *
 * side:
 *      Order side
 *      ENUM:
 *        BUY
 *        SELL
 *
 * orderType:
 *      Order type
 *      ENUM:
 *        LIMIT
 *        MARKET
 *        STOP_LOSS
 *        STOP_LOSS_LIMIT
 *        TAKE_PROFIT
 *        TAKE_PROFIT_LIMIT
 *        LIMIT_MAKER
 *
 * timeInForce :
 *      How long an order will be active before expiration.
 *      GTC: Active unless the order is canceled
 *      IOC: Order will try to fill the order as much as it can before the order expires
 *      FOK: Active unless the full order cannot be filled upon execution.
 *
 * quantity :
 *      target quantity
 *
 * quoteOrderQty :
 *      Specify the total spent or received
 *
 * price :
 *      target price
 *
 * newClientOrderId :
 *      A unique id among open orders. Automatically generated if not sent
 *
 * stopPrice :
 *      sed with STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, and TAKE_PROFIT_LIMIT orders
 *
 * icebergQty :
 *      Used with LIMIT, STOP_LOSS_LIMIT, and TAKE_PROFIT_LIMIT to create an iceberg order
 *
 * newOrderRespType :
 *      Set the response JSON. ACK, RESULT, or FULL;
 *      MARKET and LIMIT order types default to FULL, all other orders default to ACK
 *
 * recvWindow :
 *      Delay accept time
 *      The value cannot be greater than 60000
 *      defaults: 5000
 *
 */

```

### New Order

```javascript
client.newOrder(symbol: string, side: string, orderType: string, options: any = {})
options:{ timeInForce, quantity, quoteOrderQty, price, newClientOrderId, stopPrice, icebergQty, newOrderRespType, recvWindow}
/**
 *
 * side:
 *      Order side
 *      ENUM:
 *        BUY
 *        SELL
 *
 * orderType:
 *      Order type
 *      ENUM:
 *        LIMIT
 *        MARKET
 *        STOP_LOSS
 *        STOP_LOSS_LIMIT
 *        TAKE_PROFIT
 *        TAKE_PROFIT_LIMIT
 *        LIMIT_MAKER
 *
 * timeInForce :
 *      How long an order will be active before expiration.
 *      GTC: Active unless the order is canceled
 *      IOC: Order will try to fill the order as much as it can before the order expires
 *      FOK: Active unless the full order cannot be filled upon execution.
 *
 * quantity :
 *      target quantity
 *
 * quoteOrderQty :
 *      Specify the total spent or received
 *
 * price :
 *      target price
 *
 * newClientOrderId :
 *      A unique id among open orders. Automatically generated if not sent
 *
 * stopPrice :
 *      sed with STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, and TAKE_PROFIT_LIMIT orders
 *
 * icebergQty :
 *      Used with LIMIT, STOP_LOSS_LIMIT, and TAKE_PROFIT_LIMIT to create an iceberg order
 *
 * newOrderRespType :
 *      Set the response JSON. ACK, RESULT, or FULL;
 *      MARKET and LIMIT order types default to FULL, all other orders default to ACK
 *
 * recvWindow :
 *      Delay accept time
 *      The value cannot be greater than 60000
 *      defaults: 5000
 *
 */

```

### cancel-order

```javascript
client.cancelOrder(symbol: string, options:any = {})
options:{ orderId, origClientOrderId, newClientOrderId}
/**
 *
 * Either orderId or origClientOrderId must be sent
 *
 * orderId:
 *      target orderId
 *
 * origClientOrderId:
 *      target origClientOrderId
 *
 * newClientOrderId:
 *      Used to uniquely identify this cancel. Automatically generated by default.
 *
 */

```

### Cancel all Open Orders on a Symbol

```javascript
client.cancelOpenOrders(symbol: string)
```

### Query Order

```javascript
client.queryOrder(symbol: string, options:any = {})
options:{ orderId, origClientOrderId}
/**
 *
 * Either orderId or origClientOrderId must be sent
 *
 * orderId:
 *      target orderId
 *
 * origClientOrderId:
 *      target origClientOrderId
 *
 */
```

### Current Open Orders

```javascript
client.openOrders(symbol: string)
```

### All Orders

```javascript
client.allOrders(symbol: string, options: any = { limit: 500 })
options:{ orderId, startTime, endTime, limit}

/**
 *
 * orderId:
 *      target orderId
 *
 * startTime:
 *      start at
 *
 * endTime:
 *      end at
 *
 * limit :
 *      Number of returned data
 *      Default 500;
 *      max 1000;
 *
 */
```

### Account Information

```javascript
client.accountInfo()
```

### Account Trade List

```javascript
client.accountTradeList(symbol: string, options:any = { limit: 500 })
options:{ orderId, startTime, endTime, fromId, limit}

/**
 *
 * orderId:
 *      target orderId
 *
 * startTime:
 *      start at
 *
 * endTime:
 *      end at
 *
 * fromId:
 *      TradeId to fetch from. Default gets most recent trades
 *
 * limit :
 *      Number of returned data
 *      Default 500;
 *      max 1000;
 *
 */
```
'''
import abc
import builtins
import datetime
import enum
import typing

import jsii
import publication
import typing_extensions

from ._jsii import *


class Base(metaclass=jsii.JSIIMeta, jsii_type="mexc-sdk.Base"):
    def __init__(self, api_key: builtins.str, api_secret: builtins.str) -> None:
        '''
        :param api_key: -
        :param api_secret: -
        '''
        jsii.create(self.__class__, self, [api_key, api_secret])

    @jsii.member(jsii_name="publicRequest")
    def public_request(
        self,
        method: builtins.str,
        path: builtins.str,
        params_obj: typing.Any = None,
    ) -> typing.Any:
        '''
        :param method: -
        :param path: -
        :param params_obj: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "publicRequest", [method, path, params_obj]))

    @jsii.member(jsii_name="signRequest")
    def sign_request(
        self,
        method: builtins.str,
        path: builtins.str,
        params_obj: typing.Any = None,
    ) -> typing.Any:
        '''
        :param method: -
        :param path: -
        :param params_obj: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "signRequest", [method, path, params_obj]))

    @builtins.property # type: ignore[misc]
    @jsii.member(jsii_name="config")
    def config(self) -> typing.Any:
        return typing.cast(typing.Any, jsii.get(self, "config"))

    @config.setter
    def config(self, value: typing.Any) -> None:
        jsii.set(self, "config", value)


class Market(Base, metaclass=jsii.JSIIMeta, jsii_type="mexc-sdk.Market"):
    def __init__(self, api_key: builtins.str, api_secret: builtins.str) -> None:
        '''
        :param api_key: -
        :param api_secret: -
        '''
        jsii.create(self.__class__, self, [api_key, api_secret])

    @jsii.member(jsii_name="aggTrades")
    def agg_trades(
        self,
        symbol: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Compressed/Aggregate Trades List.

        Note: If sending startTime and endTime, the interval must be less than one hour

        :param symbol: -
        :param options: ``[options.fromId] - id to get aggregate trades from INCLUSIVE. [options.startTime] - Timestamp in ms to get aggregate trades from INCLUSIVE. [options.endTime] - Timestamp in ms to get aggregate trades until INCLUSIVE. [options.limit] - Default 500; max 1000. ex:500``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "aggTrades", [symbol, options]))

    @jsii.member(jsii_name="avgPrice")
    def avg_price(self, symbol: builtins.str) -> typing.Any:
        '''Current Average Price.

        :param symbol: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "avgPrice", [symbol]))

    @jsii.member(jsii_name="bookTicker")
    def book_ticker(self, symbol: typing.Optional[builtins.str] = None) -> typing.Any:
        '''Symbol Order Book Ticker.

        :param symbol: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "bookTicker", [symbol]))

    @jsii.member(jsii_name="depth")
    def depth(self, symbol: builtins.str, options: typing.Any = None) -> typing.Any:
        '''Order Book.

        :param symbol: -
        :param options: ``[options.limit] - Default 100; max 5000. Valid limits:[5, 10, 20, 50, 100, 500, 1000, 5000].``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "depth", [symbol, options]))

    @jsii.member(jsii_name="exchangeInfo")
    def exchange_info(self, options: typing.Any = None) -> typing.Any:
        '''Exchange Information.

        :param options: ``[options.symbol] - symbol(optional) ex: BTCUSDT. [options.symbols] - for mutiple symbols, add comma for each symbol in string. ex: BTCUSDT,BNBBTC .``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "exchangeInfo", [options]))

    @jsii.member(jsii_name="historicalTrades")
    def historical_trades(
        self,
        symbol: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Old Trade Lookup.

        :param symbol: -
        :param options: ``[options.limit] -limit(optional) Default 500; max 1000. ex:500.``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "historicalTrades", [symbol, options]))

    @jsii.member(jsii_name="klines")
    def klines(
        self,
        symbol: builtins.str,
        interval: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Kline/Candlestick Data.

        :param symbol: -
        :param interval: -
        :param options: ``[options.startTime] [options.endTime] [options.limit] -Default 500; max 1000. ex: 500``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "klines", [symbol, interval, options]))

    @jsii.member(jsii_name="ticker24hr")
    def ticker24hr(self, symbol: typing.Optional[builtins.str] = None) -> typing.Any:
        '''24hr Ticker Price Change Statistics.

        :param symbol: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "ticker24hr", [symbol]))

    @jsii.member(jsii_name="tickerPrice")
    def ticker_price(self, symbol: typing.Optional[builtins.str] = None) -> typing.Any:
        '''Symbol Price Ticker.

        :param symbol: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "tickerPrice", [symbol]))

    @jsii.member(jsii_name="trades")
    def trades(self, symbol: builtins.str, options: typing.Any = None) -> typing.Any:
        '''Recent Trades List.

        :param symbol: -
        :param options: ``[options.limit] -limit(optional) Default 500; max 1000. ex: 500.``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "trades", [symbol, options]))


class Common(Market, metaclass=jsii.JSIIMeta, jsii_type="mexc-sdk.Common"):
    def __init__(self, api_key: builtins.str, api_secret: builtins.str) -> None:
        '''
        :param api_key: -
        :param api_secret: -
        '''
        jsii.create(self.__class__, self, [api_key, api_secret])

    @jsii.member(jsii_name="ping")
    def ping(self) -> typing.Any:
        '''Test Connectivity.'''
        return typing.cast(typing.Any, jsii.invoke(self, "ping", []))

    @jsii.member(jsii_name="time")
    def time(self) -> typing.Any:
        '''Check Server Time.'''
        return typing.cast(typing.Any, jsii.invoke(self, "time", []))


class UserData(Common, metaclass=jsii.JSIIMeta, jsii_type="mexc-sdk.UserData"):
    def __init__(self, api_key: builtins.str, api_secret: builtins.str) -> None:
        '''
        :param api_key: -
        :param api_secret: -
        '''
        jsii.create(self.__class__, self, [api_key, api_secret])

    @jsii.member(jsii_name="accountInfo")
    def account_info(self) -> typing.Any:
        '''Account Information.'''
        return typing.cast(typing.Any, jsii.invoke(self, "accountInfo", []))

    @jsii.member(jsii_name="accountTradeList")
    def account_trade_list(
        self,
        symbol: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Account Trade List.

        :param symbol: -
        :param options: ``[options.orderId] - This can only be used in combination with symbol. [options.startTime] [options.endTime] [options.fromId] - TradeId to fetch from. Default gets most recent trades. [options.limit] - default: 500, Max: 1000``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "accountTradeList", [symbol, options]))


class Trade(UserData, metaclass=jsii.JSIIMeta, jsii_type="mexc-sdk.Trade"):
    def __init__(self, api_key: builtins.str, api_secret: builtins.str) -> None:
        '''
        :param api_key: -
        :param api_secret: -
        '''
        jsii.create(self.__class__, self, [api_key, api_secret])

    @jsii.member(jsii_name="allOrders")
    def all_orders(
        self,
        symbol: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''All Orders.

        :param symbol: -
        :param options: ``[options.orderId] - If startTime and endTime are set, orderId does not need to be set [options.startTime] [options.endTime] [options.limit] - value between 1 and 1000, default is 500``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "allOrders", [symbol, options]))

    @jsii.member(jsii_name="cancelOpenOrders")
    def cancel_open_orders(self, symbol: builtins.str) -> typing.Any:
        '''Cancel all Open Orders on a Symbol.

        :param symbol: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "cancelOpenOrders", [symbol]))

    @jsii.member(jsii_name="cancelOrder")
    def cancel_order(
        self,
        symbol: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Cancel Order.

        :param symbol: -
        :param options: ``[options.orderId] [options.origClientOrderId] [options.newClientOrderId]``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "cancelOrder", [symbol, options]))

    @jsii.member(jsii_name="newOrder")
    def new_order(
        self,
        symbol: builtins.str,
        side: builtins.str,
        order_type: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''New Order.

        :param symbol: -
        :param side: -
        :param order_type: -
        :param options: ``[options.timeInForce] [options.quantity] [options.quoteOrderQty] [options.price] [options.newClientOrderId] - A unique id among open orders. Automatically generated if not sent. [options.stopPrice] - Used with STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, and TAKE_PROFIT_LIMIT orders. [options.icebergQty] - Used with LIMIT, STOP_LOSS_LIMIT, and TAKE_PROFIT_LIMIT to create an iceberg order. [options.newOrderRespType] - Set the response JSON. ACK, RESULT, or FULL; MARKET and LIMIT order types default to FULL, all other orders default to ACK. [options.recvWindow] - The value cannot be greater than 60000``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "newOrder", [symbol, side, order_type, options]))

    @jsii.member(jsii_name="newOrderTest")
    def new_order_test(
        self,
        symbol: builtins.str,
        side: builtins.str,
        order_type: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Test New Order.

        :param symbol: -
        :param side: -
        :param order_type: -
        :param options: ``[options.timeInForce] [options.quantity] [options.quoteOrderQty] [options.price] [options.newClientOrderId] - A unique id among open orders. Automatically generated if not sent. [options.stopPrice] - Used with STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, and TAKE_PROFIT_LIMIT orders. [options.icebergQty] - Used with LIMIT, STOP_LOSS_LIMIT, and TAKE_PROFIT_LIMIT to create an iceberg order. [options.newOrderRespType] - Set the response JSON. ACK, RESULT, or FULL; MARKET and LIMIT order types default to FULL, all other orders default to ACK. [options.recvWindow] - The value cannot be greater than 60000``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "newOrderTest", [symbol, side, order_type, options]))

    @jsii.member(jsii_name="openOrders")
    def open_orders(self, symbol: builtins.str) -> typing.Any:
        '''Current Open Orders.

        :param symbol: -
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "openOrders", [symbol]))

    @jsii.member(jsii_name="queryOrder")
    def query_order(
        self,
        symbol: builtins.str,
        options: typing.Any = None,
    ) -> typing.Any:
        '''Query Order.

        :param symbol: -
        :param options: ``[options.orderId] - At least one of orderId and origClientOrderId needs to be sent [options.origClientOrderId]``.
        '''
        return typing.cast(typing.Any, jsii.invoke(self, "queryOrder", [symbol, options]))


class Spot(Trade, metaclass=jsii.JSIIMeta, jsii_type="mexc-sdk.Spot"):
    def __init__(
        self,
        api_key: typing.Optional[builtins.str] = None,
        api_secret: typing.Optional[builtins.str] = None,
    ) -> None:
        '''
        :param api_key: -
        :param api_secret: -
        '''
        jsii.create(self.__class__, self, [api_key, api_secret])


__all__ = [
    "Base",
    "Common",
    "Market",
    "Spot",
    "Trade",
    "UserData",
]

publication.publish()
