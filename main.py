import argparse
import random
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import List

from loguru import logger

from config import (
    gas_unit_price,
    is_sleep,
    max_gas_amount,
    node_url,
    pool_curve_overrides,
    randomize_wallets,
    show_balance_after_swap,
    show_balance_before_swap,
    sleep_from,
    sleep_to,
    slippage_bps as default_slippage_bps,
    swap_function,
    swap_module,
    tokens_mapping,
)
from liquidswap.client import LiquidSwapClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Swap токенов в пулах Liquidswap (Aptos)"
    )
    parser.add_argument("from_token", type=str, help="Токен, который продаем")
    parser.add_argument("to_token", type=str, help="Токен, который покупаем")
    parser.add_argument(
        "from_amount",
        type=float,
        help="Минимальное количество продаваемого токена",
    )
    parser.add_argument(
        "to_amount",
        type=float,
        help="Максимальное количество продаваемого токена",
    )
    parser.add_argument(
        "--wallets",
        default="wallets.txt",
        help="Файл со списком приватных ключей (по одному в строке)",
    )
    parser.add_argument(
        "--slippage-bps",
        type=int,
        default=default_slippage_bps,
        help="Допустимое проскальзывание в базисных пунктах (1 bp = 0.01%)",
    )
    return parser.parse_args()


def load_wallets(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"Не найден файл {path}")

    with path.open("r", encoding="utf-8-sig") as file:
        wallets = [line.strip() for line in file if line.strip()]

    if not wallets:
        raise ValueError(f"Файл {path} не содержит приватных ключей")

    return wallets


def clamp_amount(amount: float) -> float:
    decimal_amount = Decimal(str(amount)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    return float(decimal_amount)


def compute_min_output(expected: Decimal, slippage_bps: int) -> Decimal:
    tolerance = Decimal(slippage_bps) / Decimal(10_000)
    multiplier = Decimal(1) - tolerance
    if multiplier <= 0:
        return Decimal(0)
    minimum = expected * multiplier
    return minimum.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)


def main() -> None:
    args = parse_args()

    if args.from_amount <= 0 or args.to_amount <= 0:
        raise ValueError("Диапазон сумм должен быть положительным")
    if args.from_amount > args.to_amount:
        raise ValueError("Минимальная сумма больше максимальной")

    wallets = load_wallets(Path(args.wallets))
    if randomize_wallets:
        random.shuffle(wallets)

    for index, private_key in enumerate(wallets, start=1):
        logger.info(f"Кошелек {index}/{len(wallets)}")

        client = LiquidSwapClient(
            node_url,
            tokens_mapping,
            private_key,
            max_gas_amount=max_gas_amount,
            gas_unit_price=gas_unit_price,
            slippage_bps=args.slippage_bps,
            pool_curve_overrides=pool_curve_overrides,
            swap_module=swap_module,
            swap_function=swap_function,
        )

        amount = clamp_amount(random.uniform(args.from_amount, args.to_amount))

        try:
            if show_balance_before_swap:
                logger.info(
                    "Баланс до свапа: %s %s; %s %s",
                    args.from_token,
                    client.get_token_balance(args.from_token),
                    args.to_token,
                    client.get_token_balance(args.to_token),
                )

            expected_out = client.quote_exact_in(args.from_token, args.to_token, amount)
            min_receive = compute_min_output(expected_out, args.slippage_bps)

            logger.warning(
                "Свап %s %s → ~%s %s (минимум %s)",
                amount,
                args.from_token,
                expected_out.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN),
                args.to_token,
                min_receive,
            )

            tx_hash = client.swap(
                args.from_token,
                args.to_token,
                amount,
                float(min_receive),
            )
            logger.success(f"Отправлена транзакция {tx_hash}")

            if show_balance_after_swap:
                logger.info(
                    "Баланс после свапа: %s %s; %s %s",
                    args.from_token,
                    client.get_token_balance(args.from_token),
                    args.to_token,
                    client.get_token_balance(args.to_token),
                )

            if is_sleep:
                wait_time = random.randint(sleep_from, sleep_to)
                logger.warning(f"Ждем {wait_time} секунд")
                time.sleep(wait_time)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Свап не выполнен: %s", exc)


if __name__ == "__main__":
    main()

