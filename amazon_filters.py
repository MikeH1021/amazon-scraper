"""
Amazon Product Filters
Filter products based on review count, BSR, price, rating, FBA status, types, etc.
"""

import re
import logging

logger = logging.getLogger(__name__)


class ProductFilter:
    """
    Filter Amazon products based on configurable criteria.

    All filter values of 0 or empty are treated as "no filter" (disabled).
    """

    def __init__(self, config=None):
        """
        Initialize filter from a config dict.

        Args:
            config: Dict with filter keys. All fields are optional.
                - min_reviews: Minimum review count
                - max_reviews: Maximum review count
                - min_bsr: Minimum BSR rank
                - max_bsr: Maximum BSR rank
                - min_price: Minimum price
                - max_price: Maximum price
                - min_rating: Minimum star rating (0-5)
                - fba_only: Only include FBA products (bool)
                - product_types: List of product type strings to include
                - excluded_brands: List of brand names to exclude
                - title_keywords: List of keywords that must appear in title
                - min_monthly_units: Minimum estimated monthly units
                - max_monthly_units: Maximum estimated monthly units
                - min_monthly_revenue: Minimum estimated monthly revenue
                - max_monthly_revenue: Maximum estimated monthly revenue
        """
        config = config or {}
        self.min_reviews = int(config.get("min_reviews", 0))
        self.max_reviews = int(config.get("max_reviews", 0))
        self.min_bsr = int(config.get("min_bsr", 0))
        self.max_bsr = int(config.get("max_bsr", 0))
        self.min_price = float(config.get("min_price", 0))
        self.max_price = float(config.get("max_price", 0))
        self.min_rating = float(config.get("min_rating", 0))
        self.fba_only = bool(config.get("fba_only", False))
        self.product_types = [
            t.lower().strip() for t in config.get("product_types", []) if t
        ]
        self.excluded_brands = [
            b.lower().strip() for b in config.get("excluded_brands", []) if b
        ]
        self.title_keywords = [
            k.lower().strip() for k in config.get("title_keywords", []) if k
        ]
        self.min_monthly_units = int(config.get("min_monthly_units", 0))
        self.max_monthly_units = int(config.get("max_monthly_units", 0))
        self.min_monthly_revenue = float(config.get("min_monthly_revenue", 0))
        self.max_monthly_revenue = float(config.get("max_monthly_revenue", 0))

    def matches(self, product):
        """
        Check if a product matches all active filters.

        Args:
            product: Dict with product data fields

        Returns:
            True if product passes all filters, False otherwise
        """
        # Review count filter
        review_count = _safe_int(product.get("review_count", 0))
        if self.min_reviews and review_count < self.min_reviews:
            return False
        if self.max_reviews and review_count > self.max_reviews:
            return False

        # BSR filter
        bsr = _safe_int(product.get("bsr", 0))
        if self.min_bsr and bsr > 0 and bsr < self.min_bsr:
            return False
        if self.max_bsr and bsr > self.max_bsr:
            return False

        # Price filter
        price = _safe_float(product.get("price", 0))
        if self.min_price and price > 0 and price < self.min_price:
            return False
        if self.max_price and price > self.max_price:
            return False

        # Rating filter
        rating = _safe_float(product.get("rating", 0))
        if self.min_rating and rating > 0 and rating < self.min_rating:
            return False

        # FBA filter
        if self.fba_only:
            is_fba = product.get("is_fba", False)
            is_prime = product.get("is_prime", False)
            if not is_fba and not is_prime:
                return False

        # Product type filter
        if self.product_types:
            product_type = (product.get("product_type", "") or "").lower()
            title = (product.get("title", "") or "").lower()
            # Check if any allowed type appears in product_type or title
            type_match = False
            for pt in self.product_types:
                if pt in product_type or pt in title:
                    type_match = True
                    break
            if not type_match:
                return False

        # Excluded brands filter
        if self.excluded_brands:
            brand = (product.get("brand", "") or "").lower().strip()
            if brand and brand in self.excluded_brands:
                return False

        # Title keywords filter (all keywords must appear)
        if self.title_keywords:
            title = (product.get("title", "") or "").lower()
            for kw in self.title_keywords:
                if kw not in title:
                    return False

        # Monthly units filter
        monthly_units = _safe_int(product.get("estimated_monthly_units", 0))
        if self.min_monthly_units and monthly_units > 0 and monthly_units < self.min_monthly_units:
            return False
        if self.max_monthly_units and monthly_units > self.max_monthly_units:
            return False

        # Monthly revenue filter
        monthly_revenue = _safe_float(product.get("estimated_monthly_revenue", 0))
        if self.min_monthly_revenue and monthly_revenue > 0 and monthly_revenue < self.min_monthly_revenue:
            return False
        if self.max_monthly_revenue and monthly_revenue > self.max_monthly_revenue:
            return False

        return True

    def apply(self, products):
        """
        Filter a list of products, returning only those that match.

        Args:
            products: List of product dicts

        Returns:
            Filtered list of product dicts
        """
        if not products:
            return []

        before = len(products)
        filtered = [p for p in products if self.matches(p)]
        after = len(filtered)

        if before != after:
            logger.info(f"Filter applied: {before} -> {after} products ({before - after} removed)")

        return filtered

    def to_dict(self):
        """Serialize filter config to dict."""
        return {
            "min_reviews": self.min_reviews,
            "max_reviews": self.max_reviews,
            "min_bsr": self.min_bsr,
            "max_bsr": self.max_bsr,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "min_rating": self.min_rating,
            "fba_only": self.fba_only,
            "product_types": self.product_types,
            "excluded_brands": self.excluded_brands,
            "title_keywords": self.title_keywords,
            "min_monthly_units": self.min_monthly_units,
            "max_monthly_units": self.max_monthly_units,
            "min_monthly_revenue": self.min_monthly_revenue,
            "max_monthly_revenue": self.max_monthly_revenue,
        }

    def is_active(self):
        """Check if any filters are enabled."""
        return (
            self.min_reviews > 0
            or self.max_reviews > 0
            or self.min_bsr > 0
            or self.max_bsr > 0
            or self.min_price > 0
            or self.max_price > 0
            or self.min_rating > 0
            or self.fba_only
            or len(self.product_types) > 0
            or len(self.excluded_brands) > 0
            or len(self.title_keywords) > 0
            or self.min_monthly_units > 0
            or self.max_monthly_units > 0
            or self.min_monthly_revenue > 0
            or self.max_monthly_revenue > 0
        )


def _safe_int(val):
    """Safely convert a value to int."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        # Remove commas and non-numeric chars except digits
        cleaned = re.sub(r'[^\d]', '', val)
        return int(cleaned) if cleaned else 0
    return 0


def _safe_float(val):
    """Safely convert a value to float."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        # Remove $ and commas
        cleaned = re.sub(r'[^\d.]', '', val)
        return float(cleaned) if cleaned else 0.0
    return 0.0
