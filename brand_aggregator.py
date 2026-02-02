"""
Brand Aggregator
Groups Amazon products by brand and computes aggregate statistics
"""

import re
import csv
import json
import logging
from collections import defaultdict
from bsr_calculator import estimate_monthly_sales, estimate_monthly_revenue

logger = logging.getLogger(__name__)


class BrandAggregator:
    """
    Aggregates product data by normalized brand name.

    Computes per-brand:
    - total_products, total_reviews, avg_rating
    - price_min, price_max, price_avg
    - avg_bsr, best_bsr
    - estimated_monthly_units, estimated_monthly_revenue
    - fba_percentage
    - product_types (set)
    - top_product (by review count)
    """

    def __init__(self, category_key="default"):
        self.category_key = category_key
        self.brands = defaultdict(lambda: {
            "products": [],
            "total_reviews": 0,
            "ratings": [],
            "prices": [],
            "bsrs": [],
            "fba_count": 0,
            "product_types": set(),
            "monthly_units": 0,
            "monthly_revenue": 0.0,
        })

    @staticmethod
    def normalize_brand(brand_name):
        """Normalize brand name for consistent grouping."""
        if not brand_name:
            return "Unknown"
        # Strip whitespace, title case
        name = brand_name.strip()
        # Remove common suffixes
        for suffix in [", Inc.", ", LLC", " LLC", " Inc.", " Corp.", " Ltd.", " Co."]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        # Normalize whitespace
        name = re.sub(r'\s+', ' ', name).strip()
        return name if name else "Unknown"

    def add_product(self, product):
        """Add a product to the brand aggregation."""
        brand = self.normalize_brand(product.get("brand", ""))
        data = self.brands[brand]

        data["products"].append(product)

        # Reviews
        review_count = _safe_int(product.get("review_count", 0))
        data["total_reviews"] += review_count

        # Rating
        rating = _safe_float(product.get("rating", 0))
        if rating > 0:
            data["ratings"].append(rating)

        # Price
        price = _safe_float(product.get("price", 0))
        if price > 0:
            data["prices"].append(price)

        # BSR
        bsr = _safe_int(product.get("bsr", 0))
        if bsr > 0:
            data["bsrs"].append(bsr)
            units = estimate_monthly_sales(bsr, self.category_key)
            revenue = estimate_monthly_revenue(bsr, self.category_key, price)
            data["monthly_units"] += units
            data["monthly_revenue"] += revenue

        # FBA
        is_fba = product.get("is_fba", False) or product.get("is_prime", False)
        if is_fba:
            data["fba_count"] += 1

        # Product type
        product_type = product.get("product_type", "")
        if product_type:
            data["product_types"].add(product_type)

    def add_products(self, products):
        """Add multiple products at once."""
        for product in products:
            self.add_product(product)
        logger.info(f"Aggregated {len(products)} products into {len(self.brands)} brands")

    def get_brand_stats(self):
        """
        Compute brand-level statistics.

        Returns:
            Dict mapping brand name to stats dict
        """
        stats = {}
        for brand, data in self.brands.items():
            num_products = len(data["products"])
            if num_products == 0:
                continue

            prices = data["prices"]
            bsrs = data["bsrs"]
            ratings = data["ratings"]

            # Find top product by review count
            top_product = max(
                data["products"],
                key=lambda p: _safe_int(p.get("review_count", 0)),
            )

            stats[brand] = {
                "brand": brand,
                "total_products": num_products,
                "total_reviews": data["total_reviews"],
                "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
                "price_min": round(min(prices), 2) if prices else 0,
                "price_max": round(max(prices), 2) if prices else 0,
                "price_avg": round(sum(prices) / len(prices), 2) if prices else 0,
                "avg_bsr": round(sum(bsrs) / len(bsrs)) if bsrs else 0,
                "best_bsr": min(bsrs) if bsrs else 0,
                "estimated_monthly_units": data["monthly_units"],
                "estimated_monthly_revenue": round(data["monthly_revenue"], 2),
                "fba_percentage": round(data["fba_count"] / num_products * 100, 1),
                "product_types": sorted(data["product_types"]),
                "top_product_title": top_product.get("title", ""),
                "top_product_asin": top_product.get("asin", ""),
                "top_product_reviews": _safe_int(top_product.get("review_count", 0)),
            }

        return stats

    def to_brand_rows(self):
        """
        Generate flat rows for CSV export.

        Returns:
            List of dicts suitable for CSV DictWriter
        """
        stats = self.get_brand_stats()
        rows = []
        for brand_name in sorted(stats.keys(), key=lambda b: stats[b]["estimated_monthly_revenue"], reverse=True):
            s = stats[brand_name]
            rows.append({
                "brand": s["brand"],
                "total_products": s["total_products"],
                "total_reviews": s["total_reviews"],
                "avg_rating": s["avg_rating"],
                "price_min": s["price_min"],
                "price_max": s["price_max"],
                "price_avg": s["price_avg"],
                "avg_bsr": s["avg_bsr"],
                "best_bsr": s["best_bsr"],
                "estimated_monthly_units": s["estimated_monthly_units"],
                "estimated_monthly_revenue": s["estimated_monthly_revenue"],
                "fba_percentage": s["fba_percentage"],
                "product_types": ", ".join(s["product_types"]),
                "top_product_title": s["top_product_title"],
                "top_product_asin": s["top_product_asin"],
                "top_product_reviews": s["top_product_reviews"],
            })
        return rows

    def to_nested_json(self):
        """
        Generate nested JSON output with brand and product details.

        Returns:
            List of brand dicts with nested products
        """
        stats = self.get_brand_stats()
        result = []

        for brand_name in sorted(stats.keys(), key=lambda b: stats[b]["estimated_monthly_revenue"], reverse=True):
            s = stats[brand_name]
            brand_data = dict(s)
            # Include product list
            brand_data["products"] = self.brands[brand_name]["products"]
            result.append(brand_data)

        return result

    def save_brands_csv(self, filename):
        """Save brand-level data to CSV."""
        rows = self.to_brand_rows()
        if not rows:
            logger.warning("No brand data to save")
            return

        fieldnames = list(rows[0].keys())
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        logger.info(f"Saved {len(rows)} brands to {filename}")

    def save_json(self, filename):
        """Save full nested JSON output."""
        data = self.to_nested_json()
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"Saved {len(data)} brands to {filename}")


def _safe_int(val):
    """Safely convert value to int."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        cleaned = re.sub(r'[^\d]', '', val)
        return int(cleaned) if cleaned else 0
    return 0


def _safe_float(val):
    """Safely convert value to float."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r'[^\d.]', '', val)
        return float(cleaned) if cleaned else 0.0
    return 0.0
