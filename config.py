node_url = "https://fullnode.mainnet.aptoslabs.com/v1"

tokens_mapping = {
    "APT": "0x1::aptos_coin::AptosCoin",
    "USDT": "0xf22bede237a07e121b56d91a491eb7bcdfd1f5907926a9e58338f964a01b17fa::asset::USDT"
}

# Максимальное количество газа для транзакции
max_gas_amount = 50_000
# Цена за единицу газа (в окте) по умолчанию
gas_unit_price = 100

# Базовый допуск проскальзывания в базисных пунктах (50 = 0.5%)
slippage_bps = 50

# Необязательные переопределения типа пула: {("TOKEN_X", "TOKEN_Y"): "Stable"}
pool_curve_overrides = {}

# Модуль и функция свапа Liquidswap Router; оставьте None для значений по умолчанию
swap_module = None
swap_function = "swap_exact_coin_for_coin"

# Если хотите, чтобы в логах был баланс до свапа ставьте True, если нет, то False
show_balance_before_swap = True
# Если хотите, чтобы в логах был баланс после свапа ставьте True, если нет, то False
show_balance_after_swap = True
# Если хотите рандомизировать кошельки, то ставьте True, если нет, то False
randomize_wallets = True
# Если хотите делать паузы между кошельками, то ставьте True, если нет, то False
is_sleep = True
# Количество секунд паузы между кошельками
sleep_from = 100
sleep_to = 300
