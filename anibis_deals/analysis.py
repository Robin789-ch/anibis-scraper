"""Rank unusually cheap MacBook offers."""

import math
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd


def _market(database: Path) -> pd.DataFrame:
    with closing(sqlite3.connect(database)) as connection:
        market = pd.read_sql_query(
            """
            SELECT offers.*, parsed.serie, parsed.generationCPU, parsed.familyCPU,
                   parsed.RAM, parsed.storageSize, parsed.screenSize,
                   parsed.damaged, parsed.batteryHealth, parsed.year
            FROM offers JOIN parsed USING (listingID)
            WHERE parsed.serie != 'Other'
              AND parsed.generationCPU != 'Other'
              AND parsed.damaged = 0
            """,
            connection,
        )

    market["price"] = pd.to_numeric(
        market["price"].str.replace(r"\D", "", regex=True), errors="coerce"
    )
    market["storageGB"] = pd.to_numeric(
        market["storageSize"], errors="coerce"
    ).replace({500: 512, 1000: 1024, 2000: 2048})
    return market.loc[market["price"].gt(0)].copy()


def rank_prospects(market: pd.DataFrame) -> pd.DataFrame:
    """Apply the notebook's robust log-price model and rank best value first."""
    if market.empty:
        return market.assign(expectedPrice=pd.Series(dtype=float), rankPosition=0)

    blocks = [np.ones((len(market), 1))]
    for column in ["serie", "generationCPU", "familyCPU", "screenSize"]:
        blocks.append(
            pd.get_dummies(
                market[column].astype(str), prefix=column, drop_first=True, dtype=float
            ).to_numpy()
        )

    for column in ["RAM", "storageGB", "year"]:
        values = pd.to_numeric(market[column], errors="coerce").astype(float)
        missing = values.isna() | values.le(0)
        observed = values.loc[~missing]
        fallback = 2023 if column == "year" else 1
        filled = values.mask(missing, observed.median() if len(observed) else fallback)
        if column in {"RAM", "storageGB"}:
            filled = np.log2(filled)
        spread = filled.std()
        normalized = (filled - filled.mean()) / (
            spread if pd.notna(spread) and spread else 1
        )
        blocks.extend(
            [normalized.to_numpy()[:, None], missing.astype(float).to_numpy()[:, None]]
        )

    battery = pd.to_numeric(market["batteryHealth"], errors="coerce")
    blocks.append(
        battery.where(battery.between(1, 100), 90)
        .sub(90)
        .div(10)
        .to_numpy()[:, None]
    )

    matrix = np.hstack(blocks)
    log_price = np.log(market["price"].to_numpy(dtype=float))
    weights = np.ones(len(log_price))
    for _ in range(40):
        root_weights = np.sqrt(weights)
        coefficients = np.linalg.lstsq(
            matrix * root_weights[:, None], log_price * root_weights, rcond=None
        )[0]
        residual = log_price - matrix @ coefficients
        center = np.median(residual)
        scale = 1.4826 * np.median(np.abs(residual - center)) + 1e-9
        scaled = np.abs(residual - center) / (1.345 * scale)
        new_weights = np.divide(
            1, scaled, out=np.ones_like(scaled), where=scaled > 1
        )
        if np.max(np.abs(new_weights - weights)) < 1e-6:
            break
        weights = new_weights

    ranked = market.copy()
    ranked["expectedPrice"] = np.exp(matrix @ coefficients)
    residual = np.log(ranked["price"]) - np.log(ranked["expectedPrice"])
    order = ranked.iloc[
        np.lexsort((ranked["listingID"].astype(str).to_numpy(), residual.to_numpy()))
    ].index
    ranked["rankPosition"] = pd.Series(np.arange(1, len(ranked) + 1), index=order)
    return ranked.sort_values("rankPosition")


def find_best_prospects(database: Path, top_share: float = 0.01) -> list[dict]:
    """Return the best ``top_share`` of usable listings."""
    if not 0 < top_share <= 1:
        raise ValueError("top_share must be between 0 and 1")
    ranked = rank_prospects(_market(database))
    if ranked.empty:
        return []
    count = max(1, math.ceil(top_share * len(ranked)))
    return ranked.head(count).to_dict("records")
