# aptos-liquidswap-swap

Скрипт для свапов в сети Aptos с использованием DEX Liquidswap на основе официального `aptos-sdk`.

#### Установка зависимостей: ```pip install -r requirements.txt```

- `wallets.txt` для ввода приватников
- `config.py`  дефолтные настройки, также можно настроить время ожидания между кошельками, включить рандомизацию кошельков, параметры газа и проскальзывания
- `tokens_mapping` в `config.py` используется для мапинга токенов (если вам надо какой-то еще, то просто добавьте удобное для вас название и адрес нового токена)
- `max_gas_amount`, `gas_unit_price`, `slippage_bps`, `pool_curve_overrides`, `swap_module`, `swap_function` позволяют гибко настроить работу маршрутизатора Liquidswap под актуальные изменения сети Aptos

### Примеры использования

Для ввода `from_token`, `to_token`, `from_amount`, `to_amount` (надеюсь по названию понятно что это) используются аргументы командной
строки.

#### Формат команды с аргументами:

`python main.py from_token to_token from_amount to_amount [--slippage-bps N]`

Опциональный флаг `--slippage-bps` задает проскальзывание в базисных пунктах (по умолчанию берется значение `slippage_bps` из `config.py`).

1. Первый аргумент: `from_token`, указывает из какого токена делать свапы

2. Второй аргумент: `to_token`, указывает в какой токен делать свапы

3. Третий аргумент: `from_amount`, указывает от какого количества монет делать свапы

4. Четвертый аргумент: `to_amount`, указывает до какого количества монет делать свапы

#### Для свапа от 0.5 до 1 USDT в APT нужно ипользовать команду:

`python main.py USDT APT 0.5 1`

#### Для свапа от 0.7 до 0.9 APT в USDT нужно ипользовать команду:

`python main.py APT USDT 0.7 0.9`

#### Для свапа от 1 до 2.3 USDT в APT нужно ипользовать команду:

`python main.py USDT APT 1 2.3`

### Пример работы

Свап от 0.1 до 0.4 USDT в APT

![alt text](photos/liquidswap-example-updated.png)

### Telegram https://t.me/sybil_v_zakone

_В основе лежит репозиторий: https://github.com/WayneAl/liquidswap-sdk-python_
