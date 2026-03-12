"""
Amazon Scraper Presets
Pre-configured search profiles for common research scenarios
"""

PRESETS = {
    "ally_nutra": {
        "name": "Ally Nutra",
        "description": "Supplements & nutraceuticals research for Ally Nutra brand analysis",
        "categories": ["health"],
        "subcategories": ["vitamins", "sports_nutrition", "herbal_supplements"],
        "keywords": [
            "ashwagandha supplement",
            "turmeric curcumin",
            "magnesium glycinate",
            "vitamin d3 k2",
            "collagen peptides",
            "probiotics digestive",
            "omega 3 fish oil",
            "berberine supplement",
            "mushroom supplement",
            "sea moss supplement",
            "electrolyte powder",
            "greens powder supplement",
        ],
        "filters": {
            "min_reviews": 0,
            "max_reviews": 0,
            "min_bsr": 0,
            "max_bsr": 0,
            "min_price": 0,
            "max_price": 0,
            "min_rating": 0,
            "fba_only": False,
            "product_types": [],
            "excluded_brands": [],
            "title_keywords": [],
        },
        "max_pages": 3,
        "detail_pages": False,
        "output_format": "both",
    },
    "blank": {
        "name": "Blank Template",
        "description": "Empty configuration - customize everything from scratch",
        "categories": [],
        "subcategories": [],
        "keywords": [],
        "filters": {
            "min_reviews": 0,
            "max_reviews": 0,
            "min_bsr": 0,
            "max_bsr": 0,
            "min_price": 0,
            "max_price": 0,
            "min_rating": 0,
            "fba_only": False,
            "product_types": [],
            "excluded_brands": [],
            "title_keywords": [],
        },
        "max_pages": 3,
        "detail_pages": False,
        "output_format": "csv",
    },
    "beauty_private_label": {
        "name": "Beauty Private Label",
        "description": "Private label beauty product opportunities",
        "categories": ["beauty"],
        "subcategories": ["skin_care", "hair_care"],
        "keywords": [
            "vitamin c serum",
            "retinol cream",
            "hyaluronic acid serum",
            "hair growth oil",
            "biotin shampoo",
            "tea tree oil",
            "rosehip oil face",
            "collagen face cream",
        ],
        "filters": {
            "min_reviews": 0,
            "max_reviews": 0,
            "min_bsr": 0,
            "max_bsr": 0,
            "min_price": 0,
            "max_price": 0,
            "min_rating": 0,
            "fba_only": False,
            "product_types": [],
            "excluded_brands": [],
            "title_keywords": [],
        },
        "max_pages": 3,
        "detail_pages": False,
        "output_format": "both",
    },
    "home_kitchen": {
        "name": "Home & Kitchen Explorer",
        "description": "Trending home and kitchen products",
        "categories": ["home"],
        "subcategories": ["kitchen_dining", "storage"],
        "keywords": [
            "kitchen organizer",
            "spice rack",
            "cutting board",
            "food storage containers",
            "silicone baking mat",
            "water bottle stainless steel",
        ],
        "filters": {
            "min_reviews": 0,
            "max_reviews": 0,
            "min_bsr": 0,
            "max_bsr": 0,
            "min_price": 0,
            "max_price": 0,
            "min_rating": 0,
            "fba_only": False,
            "product_types": [],
            "excluded_brands": [],
            "title_keywords": [],
        },
        "max_pages": 3,
        "detail_pages": False,
        "output_format": "csv",
    },
}


def get_preset(name):
    """Get a preset by name. Returns None if not found."""
    return PRESETS.get(name)


def get_all_presets():
    """Get summary of all presets (name, description only)."""
    result = {}
    for key, preset in PRESETS.items():
        result[key] = {
            "name": preset["name"],
            "description": preset["description"],
        }
    return result


def get_preset_full(name):
    """Get full preset configuration by name."""
    return PRESETS.get(name)
