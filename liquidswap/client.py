from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, getcontext
from typing import Dict, Iterable, Optional, Tuple

from loguru import logger

from aptos_sdk import ed25519
from aptos_sdk.account import Account
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.bcs import Serializer
from aptos_sdk.client import ApiError, ClientConfig, RestClient
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.type_tag import StructTag, TypeTag

from .constants import (
    COIN_INFO,
    COIN_STORE,
    CURVE_NAME_TO_TYPE,
    CURVE_TYPES,
    CURVE_UNCORRELATED,
    DEFAULT_CURVE,
    FEE_PCT,
    FEE_SCALE,
    FUNGIBLE_ASSET_METADATA,
    FUNGIBLE_ASSET_STORE,
    NETWORKS_MODULES,
    RESOURCES_ACCOUNT,
)


getcontext().prec = 28


@dataclass(frozen=True)
class PoolState:
    """Содержит текущие параметры пула ликвидности."""

    coin_x_type: str
    coin_y_type: str
    coin_x_reserve: int
    coin_y_reserve: int
    curve: str


class LiquidSwapClient(RestClient):
    """Клиент для работы с пулами Liquidswap поверх официального Aptos SDK."""

    def __init__(
        self,
        node_url: str,
        tokens_mapping: Dict[str, str],
        hex_private_key: str,
        *,
        max_gas_amount: int = 50_000,
        gas_unit_price: int = 100,
        slippage_bps: int = 50,
        pool_curve_overrides: Optional[Dict[Tuple[str, str], str]] = None,
        swap_module: Optional[str] = None,
        swap_function: str = "swap_exact_coin_for_coin",
    ) -> None:
        client_config = ClientConfig()
        client_config.max_gas_amount = max_gas_amount
        client_config.gas_unit_price = gas_unit_price
        super().__init__(node_url, client_config=client_config)

        private_key = ed25519.PrivateKey.from_hex(hex_private_key)
        self.my_account = Account(
            account_address=AccountAddress.from_key(private_key.public_key()),
            private_key=private_key,
        )

        self.tokens_mapping = tokens_mapping
        self.slippage_bps = slippage_bps
        self.pool_curve_overrides = self._prepare_overrides(pool_curve_overrides or {})
        self.swap_module = swap_module or NETWORKS_MODULES["Router"]
        self.swap_function = swap_function
        self._decimals_cache: Dict[str, int] = {}

        logger.debug(f"Аккаунт: {self.my_account.account_address}")

    # region Helpers

    def _type_for_token(self, token: str) -> str:
        return self.tokens_mapping.get(token, token)

    def resolve_token_type(self, token: str) -> str:
        """Публичный доступ к реальному типу токена."""

        return self._type_for_token(token)

    @staticmethod
    def _normalize_pair(type_a: str, type_b: str) -> Tuple[str, str]:
        return tuple(sorted((type_a, type_b)))

    def _prepare_overrides(
        self, overrides: Dict[Tuple[str, str], str]
    ) -> Dict[Tuple[str, str], str]:
        prepared: Dict[Tuple[str, str], str] = {}
        for pair, curve_name in overrides.items():
            if len(pair) != 2:
                raise ValueError("Override ключ должен содержать два токена")
            raw_type_a, raw_type_b = pair
            type_a = self._type_for_token(raw_type_a)
            type_b = self._type_for_token(raw_type_b)
            normalized = self._normalize_pair(type_a, type_b)
            curve_type = CURVE_NAME_TO_TYPE.get(curve_name, curve_name)
            if curve_type not in CURVE_TYPES:
                raise ValueError(
                    f"Неизвестный тип кривой '{curve_name}'. Допустимые: {list(CURVE_NAME_TO_TYPE)}"
                )
            prepared[normalized] = curve_type
        return prepared

    def _coin_info_address(self, token_type: str) -> AccountAddress:
        return AccountAddress.from_hex(token_type.split("::")[0])

    def _ensure_curve(self, token_x: str, token_y: str) -> str:
        try:
            pool_state, _ = self._fetch_pool_state(token_x, token_y)
            return pool_state.curve
        except RuntimeError:
            return DEFAULT_CURVE

    # endregion

    # region Coin metadata helpers

    def get_coin_info(self, token: str) -> int:
        token_type = self._type_for_token(token)
        if token_type in self._decimals_cache:
            return self._decimals_cache[token_type]
        account_address = self._coin_info_address(token_type)
        resource_type = f"{COIN_INFO}<{token_type}>"

        try:
            resource = self.account_resource(account_address, resource_type)
            decimals = int(resource["data"]["decimals"])
        except ApiError:
            metadata_type = f"{FUNGIBLE_ASSET_METADATA}<{token_type}>"
            metadata = self.account_resource(account_address, metadata_type)["data"]
            decimals = metadata.get("decimals") or metadata.get("supply", {}).get("decimals")
            if decimals is None:
                raise
            decimals = int(decimals)

        self._decimals_cache[token_type] = decimals
        return decimals

    def convert_to_decimals(self, amount: float, token: str) -> int:
        decimals = self.get_coin_info(token)
        scaled = Decimal(str(amount)) * (Decimal(10) ** decimals)
        return int(scaled.quantize(Decimal(1), rounding=ROUND_DOWN))

    def pretty_amount(self, amount: int, token: str) -> Decimal:
        decimals = self.get_coin_info(token)
        return Decimal(amount) / (Decimal(10) ** decimals)

    # endregion

    # region Pool helpers

    def _candidate_curves(self, type_a: str, type_b: str) -> Iterable[str]:
        override = self.pool_curve_overrides.get(self._normalize_pair(type_a, type_b))
        if override:
            return (override,)
        return CURVE_TYPES

    def _fetch_pool_state(
        self,
        token_x: str,
        token_y: str,
    ) -> Tuple[PoolState, bool]:
        type_x = self._type_for_token(token_x)
        type_y = self._type_for_token(token_y)

        for curve in self._candidate_curves(type_x, type_y):
            for primary, secondary in ((type_x, type_y), (type_y, type_x)):
                resource_type = (
                    f"{NETWORKS_MODULES['LiquidityPool']}::LiquidityPool<"
                    f"{primary}, {secondary}, {curve}>"
                )
                try:
                    resource = self.account_resource(
                        AccountAddress.from_hex(RESOURCES_ACCOUNT), resource_type
                    )
                    data = resource["data"]
                    pool_state = PoolState(
                        coin_x_type=primary,
                        coin_y_type=secondary,
                        coin_x_reserve=int(data["coin_x_reserve"]["value"]),
                        coin_y_reserve=int(data["coin_y_reserve"]["value"]),
                        curve=curve,
                    )
                    inverted = primary != type_x
                    return pool_state, inverted
                except ApiError:
                    continue
        raise RuntimeError(f"Пул {token_x}/{token_y} не найден")

    def get_token_reserves(self, token_x: str, token_y: str) -> Tuple[Decimal, Decimal, str]:
        pool_state, inverted = self._fetch_pool_state(token_x, token_y)

        if inverted:
            from_reserve_raw = pool_state.coin_y_reserve
            to_reserve_raw = pool_state.coin_x_reserve
        else:
            from_reserve_raw = pool_state.coin_x_reserve
            to_reserve_raw = pool_state.coin_y_reserve

        from_reserve = self.pretty_amount(from_reserve_raw, token_x)
        to_reserve = self.pretty_amount(to_reserve_raw, token_y)

        return from_reserve, to_reserve, pool_state.curve

    # endregion

    def quote_exact_in(self, from_token: str, to_token: str, amount: float) -> Decimal:
        from_reserve, to_reserve, curve = self.get_token_reserves(from_token, to_token)

        amount_dec = Decimal(str(amount))
        if amount_dec <= 0:
            raise ValueError("Количество для свапа должно быть положительным")

        if curve != CURVE_UNCORRELATED:
            raise ValueError(
                "Расчёт квоты для Stable пулов не реализован. Укажите override в config.py."
            )

        fee_multiplier = Decimal(FEE_SCALE - FEE_PCT) / Decimal(FEE_SCALE)
        amount_after_fee = amount_dec * fee_multiplier

        numerator = amount_after_fee * to_reserve
        denominator = from_reserve + amount_after_fee
        if denominator == 0:
            raise ValueError("Некорректные резервы пула")

        return numerator / denominator

    def get_token_balance(self, token: str) -> Decimal:
        coin_data = self.get_coin_data(token)
        if coin_data is None:
            return Decimal(0)
        return self.pretty_amount(int(coin_data), token)

    def get_coin_data(self, token: str) -> Optional[str]:
        token_type = self._type_for_token(token)
        address = self.my_account.address()

        try:
            coin_store = self.account_resource(address, f"{COIN_STORE}<{token_type}>")
            return (
                coin_store.get("data", {})
                .get("coin", {})
                .get("value")
            )
        except ApiError:
            pass

        try:
            fa_store = self.account_resource(address, f"{FUNGIBLE_ASSET_STORE}<{token_type}>")
            balance = fa_store.get("data", {}).get("balance")
            if isinstance(balance, dict):
                return balance.get("value")
            return balance
        except ApiError:
            return None

    def register(self, token: str) -> None:
        token_type = self._type_for_token(token)

        payload = EntryFunction.natural(
            "0x1::managed_coin",
            "register",
            [TypeTag(StructTag.from_str(token_type))],
            [],
        )

        signed_transaction = self.create_bcs_signed_transaction(
            self.my_account, TransactionPayload(payload)
        )
        tx = self.submit_bcs_transaction(signed_transaction)
        self.wait_for_transaction(tx)
        logger.success(
            "Успешно зарегистрирована монета {token}.\nHash: "
            "https://explorer.aptoslabs.com/txn/{tx}?network=mainnet".format(token=token, tx=tx)
        )

    def swap(
        self,
        from_token: str,
        to_token: str,
        from_amount: float,
        min_receive_amount: float,
    ) -> str:
        if self.get_coin_data(to_token) is None:
            logger.info(f"Регистрируем токен {to_token}")
            self.register(to_token)

        curve_type = self._ensure_curve(from_token, to_token)

        payload = EntryFunction.natural(
            self.swap_module,
            self.swap_function,
            [
                TypeTag(StructTag.from_str(self._type_for_token(from_token))),
                TypeTag(StructTag.from_str(self._type_for_token(to_token))),
                TypeTag(StructTag.from_str(curve_type)),
            ],
            [
                TransactionArgument(
                    self.convert_to_decimals(from_amount, from_token),
                    Serializer.u64,
                ),
                TransactionArgument(
                    self.convert_to_decimals(min_receive_amount, to_token),
                    Serializer.u64,
                ),
            ],
        )

        signed_transaction = self.create_bcs_signed_transaction(
            self.my_account, TransactionPayload(payload)
        )
        tx = self.submit_bcs_transaction(signed_transaction)
        self.wait_for_transaction(tx)
        logger.success(
            "Транзакция успешно выполнена.\nHash: "
            "https://explorer.aptoslabs.com/txn/{tx}?network=mainnet".format(tx=tx)
        )
        return tx

