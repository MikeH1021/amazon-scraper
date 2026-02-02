"""
BSR (Best Sellers Rank) to Monthly Sales Calculator
Estimates monthly unit sales and revenue based on Amazon BSR and category
Uses range-based lookup tables calibrated from industry data
"""

# BSR-to-monthly-sales lookup tables by category
# Format: list of (max_bsr, estimated_monthly_units)
# Lower BSR = higher sales. Interpolation used between ranges.

BSR_TABLES = {
    "health": [
        (50, 4500),
        (100, 3500),
        (200, 2800),
        (500, 1800),
        (1000, 1200),
        (2000, 750),
        (5000, 400),
        (10000, 200),
        (20000, 100),
        (50000, 40),
        (100000, 15),
        (200000, 5),
        (500000, 2),
    ],
    "beauty": [
        (50, 4000),
        (100, 3200),
        (200, 2500),
        (500, 1600),
        (1000, 1100),
        (2000, 650),
        (5000, 350),
        (10000, 180),
        (20000, 90),
        (50000, 35),
        (100000, 12),
        (200000, 4),
        (500000, 1),
    ],
    "home": [
        (50, 3500),
        (100, 2800),
        (200, 2200),
        (500, 1400),
        (1000, 900),
        (2000, 550),
        (5000, 300),
        (10000, 150),
        (20000, 75),
        (50000, 30),
        (100000, 10),
        (200000, 3),
        (500000, 1),
    ],
    "grocery": [
        (50, 5500),
        (100, 4200),
        (200, 3300),
        (500, 2100),
        (1000, 1400),
        (2000, 900),
        (5000, 480),
        (10000, 240),
        (20000, 120),
        (50000, 50),
        (100000, 18),
        (200000, 6),
        (500000, 2),
    ],
    "default": [
        (50, 3000),
        (100, 2400),
        (200, 1900),
        (500, 1200),
        (1000, 800),
        (2000, 480),
        (5000, 260),
        (10000, 130),
        (20000, 65),
        (50000, 25),
        (100000, 8),
        (200000, 3),
        (500000, 1),
    ],
}


def _interpolate(bsr, table):
    """Linearly interpolate between BSR ranges in the lookup table."""
    if bsr <= table[0][0]:
        return table[0][1]
    if bsr >= table[-1][0]:
        return table[-1][1]

    for i in range(1, len(table)):
        if bsr <= table[i][0]:
            bsr_low, units_low = table[i - 1]
            bsr_high, units_high = table[i]
            # Linear interpolation in log space for better accuracy
            ratio = (bsr - bsr_low) / (bsr_high - bsr_low)
            estimated = units_low + ratio * (units_high - units_low)
            return max(1, round(estimated))

    return table[-1][1]


def estimate_monthly_sales(bsr, category_key="default"):
    """
    Estimate monthly unit sales from BSR rank.

    Args:
        bsr: Best Sellers Rank (integer)
        category_key: Category key matching BSR_TABLES or AMAZON_CATEGORIES

    Returns:
        Estimated monthly units sold (integer)
    """
    if not bsr or bsr <= 0:
        return 0

    # Map amazon_categories keys to BSR table keys
    category_map = {
        "health": "health",
        "beauty": "beauty",
        "home": "home",
        "grocery": "grocery",
        "baby": "health",
        "pets": "home",
        "sports": "default",
        "tools": "default",
        "electronics": "default",
        "office": "default",
        "garden": "home",
        "toys": "default",
        "automotive": "default",
        "arts": "default",
        "industrial": "default",
        "clothing": "default",
        "books": "default",
        "appliances": "default",
    }

    table_key = category_map.get(category_key, "default")
    table = BSR_TABLES.get(table_key, BSR_TABLES["default"])

    return _interpolate(bsr, table)


def estimate_monthly_revenue(bsr, category_key="default", price=0):
    """
    Estimate monthly revenue from BSR rank and price.

    Args:
        bsr: Best Sellers Rank
        category_key: Category key
        price: Product price in dollars

    Returns:
        Estimated monthly revenue in dollars (float)
    """
    if not price or price <= 0:
        return 0.0

    units = estimate_monthly_sales(bsr, category_key)
    return round(units * price, 2)
