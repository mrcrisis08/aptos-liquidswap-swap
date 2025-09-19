import argparse
import random
import time
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import List, Optional

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

DISPLAY_PRECISION = Decimal("0.00000001")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Swap токенов в пулах Liquidswap (Aptos)"
    )
    parser.add_argument(
        "from_token",
        nargs="?",
        default=None,
        help="Токен, который продаем (не обязателен в режиме --sweep-all)",
    )
    parser.add_argument(
        "to_token",
        nargs="?",
        default=None,
        help="Токен, который покупаем (по умолчанию APT для --sweep-all)",
    )
    parser.add_argument(
        "from_amount",
        nargs="?",
        default=None,
        help="Минимальное количество продаваемого токена",
    )
    parser.add_argument(
        "to_amount",
        nargs="?",
        default=None,
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
    parser.add_argument(
        "--use-all-balance",
        action="store_true",
        help="Продает весь доступный баланс from_token вместо диапазона сумм",
    )
    parser.add_argument(
        "--sweep-all",
        action="store_true",
        help=(
            "Ищет все токены из tokens_mapping, у которых есть баланс, и меняет их на"
            " to_token (по умолчанию APT)"
        ),
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


def clamp_amount(amount: float) -> Decimal:
    return Decimal(str(amount)).quantize(DISPLAY_PRECISION, rounding=ROUND_DOWN)


def parse_positive_amount(value: Optional[str], label: str) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Не удалось распарсить {label}: {value}") from exc
    if parsed <= 0:
        raise ValueError(f"{label.capitalize()} должно быть больше нуля")
    return parsed


def compute_min_output(expected: Decimal, slippage_bps: int) -> Decimal:
    tolerance = Decimal(slippage_bps) / Decimal(10_000)
    multiplier = Decimal(1) - tolerance
    if multiplier <= 0:
        return Decimal(0)
    minimum = expected * multiplier
    return minimum.quantize(DISPLAY_PRECISION, rounding=ROUND_DOWN)


def format_amount(amount: Decimal) -> Decimal:
    return amount.quantize(DISPLAY_PRECISION, rounding=ROUND_DOWN)


def execute_swap(
    client: LiquidSwapClient,
    from_token: str,
    to_token: str,
    amount: Decimal,
    slippage_bps: int,
    *,
    known_from_balance: Optional[Decimal] = None,
) -> Optional[str]:
    if amount <= 0:
        logger.info("Баланс %s равен 0, пропускаем", from_token)
        return None

    if show_balance_before_swap:
        from_balance = (
            format_amount(known_from_balance)
            if known_from_balance is not None
            else format_amount(client.get_token_balance(from_token))
        )
        to_balance = format_amount(client.get_token_balance(to_token))
        logger.info(
            "Баланс до свапа: %s %s; %s %s",
            from_token,
            from_balance,
            to_token,
            to_balance,
        )

    expected_out = client.quote_exact_in(from_token, to_token, amount)
    min_receive = compute_min_output(expected_out, slippage_bps)

    logger.warning(
        "Свап %s %s → ~%s %s (минимум %s)",
        format_amount(amount),
        from_token,
        format_amount(expected_out),
        to_token,
        min_receive,
    )

    tx_hash = client.swap(from_token, to_token, amount, min_receive)
    logger.success(f"Отправлена транзакция {tx_hash}")

    if show_balance_after_swap:
        logger.info(
            "Баланс после свапа: %s %s; %s %s",
            from_token,
            format_amount(client.get_token_balance(from_token)),
            to_token,
            format_amount(client.get_token_balance(to_token)),
        )

    return tx_hash


def determine_amount_for_wallet(
    client: LiquidSwapClient,
    from_token: str,
    min_amount: Optional[float],
    max_amount: Optional[float],
    use_all_balance: bool,
) -> Decimal:
    if use_all_balance:
        raw_balance = client.get_coin_data(from_token)
        if raw_balance is None:
            return Decimal(0)
        balance_int = int(raw_balance)
        if balance_int <= 0:
            return Decimal(0)
        return client.pretty_amount(balance_int, from_token)

    if min_amount is None or max_amount is None:
        raise ValueError("Не задан диапазон сумм для свапа")

    random_amount = random.uniform(min_amount, max_amount)
    return clamp_amount(random_amount)


def sweep_wallet_tokens(
    client: LiquidSwapClient,
    target_token: str,
    slippage_bps: int,
) -> None:
    target_type = client.resolve_token_type(target_token)
    processed = False

    for token_name in tokens_mapping:
        token_type = client.resolve_token_type(token_name)
        if token_type == target_type:
            continue

        raw_balance = client.get_coin_data(token_name)
        if raw_balance is None:
            continue

        balance_int = int(raw_balance)
        if balance_int <= 0:
            logger.debug("Баланс %s равен 0, пропускаем", token_name)
            continue

        amount = client.pretty_amount(balance_int, token_name)

        try:
            execute_swap(
                client,
                token_name,
                target_token,
                amount,
                slippage_bps,
                known_from_balance=amount,
            )
            processed = True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Свап %s → %s не выполнен: %s", token_name, target_token, exc)

    if not processed:
        logger.info("Не найдено токенов для свапа по tokens_mapping")


def main() -> None:
    args = parse_args()

    if args.slippage_bps < 0:
        raise ValueError("Проскальзывание не может быть отрицательным")
    if args.sweep_all and args.use_all_balance:
        raise ValueError("Нельзя одновременно использовать --sweep-all и --use-all-balance")

    min_amount = parse_positive_amount(args.from_amount, "минимальное количество")
    max_amount = parse_positive_amount(args.to_amount, "максимальное количество")

    if args.sweep_all:
        if args.to_token is None and args.from_token is not None:
            args.to_token = args.from_token
            args.from_token = None
        target_token = args.to_token or "APT"
    else:
        if args.from_token is None or args.to_token is None:
            raise ValueError("Укажите токены для свапа (from_token и to_token)")
        target_token = args.to_token

    if not args.sweep_all:
        if args.use_all_balance:
            if args.from_token is None:
                raise ValueError("Для --use-all-balance необходимо указать from_token")
        else:
            if min_amount is None or max_amount is None:
                raise ValueError(
                    "Укажите from_amount/to_amount или используйте --use-all-balance"
                )
            if min_amount > max_amount:
                raise ValueError("Минимальная сумма больше максимальной")
    elif min_amount is not None or max_amount is not None:
        logger.warning("Диапазон сумм проигнорирован в режиме --sweep-all")

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

        try:
            if args.sweep_all:
                sweep_wallet_tokens(client, target_token, args.slippage_bps)
            else:
                amount = determine_amount_for_wallet(
                    client,
                    args.from_token,
                    min_amount,
                    max_amount,
                    args.use_all_balance,
                )
                execute_swap(
                    client,
                    args.from_token,
                    target_token,
                    amount,
                    args.slippage_bps,
                    known_from_balance=amount if args.use_all_balance else None,
                )

            if is_sleep:
                wait_time = random.randint(sleep_from, sleep_to)
                logger.warning(f"Ждем {wait_time} секунд")
                time.sleep(wait_time)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Свап не выполнен: %s", exc)


if __name__ == "__main__":
    main()

