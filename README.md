# aptos-liquidswap-swap

Скрипт для свапов в сети Aptos с использованием DEX Liquidswap на основе официального `aptos-sdk`.

#### Установка зависимостей: ```pip install -r requirements.txt```

- `wallets.txt` для ввода приватников
- `config.py`  дефолтные настройки, также можно настроить время ожидания между кошельками, включить рандомизацию кошельков, параметры газа и проскальзывания
- `tokens_mapping` в `config.py` используется для мапинга токенов (если вам надо какой-то еще, то просто добавьте удобное для вас название и адрес нового токена)
- `max_gas_amount`, `gas_unit_price`, `slippage_bps`, `pool_curve_overrides`, `swap_module`, `swap_function` позволяют гибко настроить работу маршрутизатора Liquidswap под актуальные изменения сети Aptos

### Примеры использования

CLI поддерживает как диапазон сумм, так и работу со всем балансом/автособором токенов.

#### Базовый формат

```
python main.py from_token to_token [from_amount to_amount] \
    [--slippage-bps N] [--use-all-balance] [--sweep-all]
```

- `from_token` — тикер или полный тип токена, который продаем.
- `to_token` — тикер или тип токена, который покупаем (для `--sweep-all` по умолчанию `APT`).
- `from_amount` и `to_amount` задают диапазон случайной суммы свапа. Они необязательны, если включен `--use-all-balance` или `--sweep-all`.
- `--slippage-bps` — допуск проскальзывания в базисных пунктах (по умолчанию берется из `config.py`).
- `--use-all-balance` — продает весь текущий баланс `from_token` без указания сумм.
- `--sweep-all` — проходит по всем токенам из `tokens_mapping`, проверяет баланс и меняет их в `to_token`.

#### Примеры

- Свап случайной суммы от 0.5 до 1 USDT в APT:
  ```
  python main.py USDT APT 0.5 1
  ```
- Свап всей доступной позиции stAPT в APT без указания суммы:
  ```
  python main.py stAPT APT --use-all-balance
  ```
- Автособор всех токенов из `tokens_mapping` в APT (по умолчанию):
  ```
  python main.py --sweep-all
  ```
- Автособор всех токенов из `tokens_mapping` в USDC (указываем токен назначения):
  ```
  python main.py USDC --sweep-all
  ```

### Пример работы

Свап от 0.1 до 0.4 USDT в APT

![alt text](photos/liquidswap-example-updated.png)

### Telegram https://t.me/sybil_v_zakone

_В основе лежит репозиторий: https://github.com/WayneAl/liquidswap-sdk-python_
