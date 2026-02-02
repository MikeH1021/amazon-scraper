"""
Amazon Product Categories
Browse nodes, search URLs, and BSR multipliers for Amazon product research
"""

AMAZON_CATEGORIES = {
    "health": {
        "name": "Health & Household",
        "browse_node": "3760901",
        "department": "hpc",
        "bsr_multiplier": 1.0,
        "subcategories": {
            "vitamins": {"name": "Vitamins & Dietary Supplements", "browse_node": "3764441"},
            "sports_nutrition": {"name": "Sports Nutrition", "browse_node": "6973663011"},
            "herbal_supplements": {"name": "Herbal Supplements", "browse_node": "3764531"},
            "health_household": {"name": "Health & Household (General)", "browse_node": "3760901"},
        }
    },
    "beauty": {
        "name": "Beauty & Personal Care",
        "browse_node": "3760911",
        "department": "beauty",
        "bsr_multiplier": 0.9,
        "subcategories": {
            "skin_care": {"name": "Skin Care", "browse_node": "11060451"},
            "hair_care": {"name": "Hair Care", "browse_node": "11057241"},
            "makeup": {"name": "Makeup", "browse_node": "11058281"},
            "fragrance": {"name": "Fragrance", "browse_node": "11056591"},
        }
    },
    "grocery": {
        "name": "Grocery & Gourmet Food",
        "browse_node": "16310101",
        "department": "grocery",
        "bsr_multiplier": 1.2,
        "subcategories": {
            "snacks": {"name": "Snack Foods", "browse_node": "16322721"},
            "beverages": {"name": "Beverages", "browse_node": "16318401"},
            "pantry": {"name": "Pantry Staples", "browse_node": "16310231"},
        }
    },
    "home": {
        "name": "Home & Kitchen",
        "browse_node": "1055398",
        "department": "garden",
        "bsr_multiplier": 0.8,
        "subcategories": {
            "kitchen_dining": {"name": "Kitchen & Dining", "browse_node": "284507"},
            "bedding": {"name": "Bedding", "browse_node": "1063252"},
            "bath": {"name": "Bath", "browse_node": "1063236"},
            "storage": {"name": "Storage & Organization", "browse_node": "553788"},
        }
    },
    "baby": {
        "name": "Baby",
        "browse_node": "165796011",
        "department": "baby-products",
        "bsr_multiplier": 0.85,
        "subcategories": {
            "feeding": {"name": "Feeding", "browse_node": "166772011"},
            "diapering": {"name": "Diapering", "browse_node": "166764011"},
            "baby_care": {"name": "Baby Care", "browse_node": "166761011"},
        }
    },
    "pets": {
        "name": "Pet Supplies",
        "browse_node": "2619533011",
        "department": "pets",
        "bsr_multiplier": 0.85,
        "subcategories": {
            "dog_supplies": {"name": "Dog Supplies", "browse_node": "2975312011"},
            "cat_supplies": {"name": "Cat Supplies", "browse_node": "2975241011"},
            "fish_aquatic": {"name": "Fish & Aquatic Pets", "browse_node": "2975446011"},
        }
    },
    "sports": {
        "name": "Sports & Outdoors",
        "browse_node": "3375251",
        "department": "sporting",
        "bsr_multiplier": 0.7,
        "subcategories": {
            "exercise_fitness": {"name": "Exercise & Fitness", "browse_node": "3407731"},
            "outdoor_recreation": {"name": "Outdoor Recreation", "browse_node": "706814011"},
            "team_sports": {"name": "Team Sports", "browse_node": "3375301"},
        }
    },
    "tools": {
        "name": "Tools & Home Improvement",
        "browse_node": "228013",
        "department": "tools",
        "bsr_multiplier": 0.65,
        "subcategories": {
            "power_tools": {"name": "Power & Hand Tools", "browse_node": "551236"},
            "hardware": {"name": "Hardware", "browse_node": "511228"},
            "lighting": {"name": "Lighting & Ceiling Fans", "browse_node": "495224"},
        }
    },
    "electronics": {
        "name": "Electronics",
        "browse_node": "172282",
        "department": "electronics",
        "bsr_multiplier": 0.5,
        "subcategories": {
            "accessories": {"name": "Accessories & Supplies", "browse_node": "281407"},
            "computers": {"name": "Computers & Accessories", "browse_node": "541966"},
            "cell_phone": {"name": "Cell Phones & Accessories", "browse_node": "2335752011"},
        }
    },
    "office": {
        "name": "Office Products",
        "browse_node": "1064954",
        "department": "office-products",
        "bsr_multiplier": 0.7,
        "subcategories": {
            "office_supplies": {"name": "Office Supplies", "browse_node": "1069242"},
            "office_furniture": {"name": "Office Furniture & Lighting", "browse_node": "1069130"},
        }
    },
    "garden": {
        "name": "Patio, Lawn & Garden",
        "browse_node": "2972638011",
        "department": "lawngarden",
        "bsr_multiplier": 0.75,
        "subcategories": {
            "gardening": {"name": "Gardening & Lawn Care", "browse_node": "2972638011"},
            "outdoor_decor": {"name": "Outdoor Decor", "browse_node": "3480662011"},
        }
    },
    "toys": {
        "name": "Toys & Games",
        "browse_node": "165793011",
        "department": "toys-and-games",
        "bsr_multiplier": 0.75,
        "subcategories": {
            "action_figures": {"name": "Action Figures & Statues", "browse_node": "166024011"},
            "building_toys": {"name": "Building Toys", "browse_node": "166092011"},
            "puzzles": {"name": "Puzzles", "browse_node": "166359011"},
        }
    },
    "automotive": {
        "name": "Automotive",
        "browse_node": "15684181",
        "department": "automotive",
        "bsr_multiplier": 0.6,
        "subcategories": {
            "car_care": {"name": "Car Care", "browse_node": "15718271"},
            "interior_accessories": {"name": "Interior Accessories", "browse_node": "15736371"},
            "exterior_accessories": {"name": "Exterior Accessories", "browse_node": "15735881"},
        }
    },
    "arts": {
        "name": "Arts, Crafts & Sewing",
        "browse_node": "2617941011",
        "department": "arts-crafts",
        "bsr_multiplier": 0.7,
        "subcategories": {
            "painting": {"name": "Painting, Drawing & Art Supplies", "browse_node": "12896111"},
            "sewing": {"name": "Sewing", "browse_node": "12899121"},
            "crafting": {"name": "Crafting", "browse_node": "12898821"},
        }
    },
    "industrial": {
        "name": "Industrial & Scientific",
        "browse_node": "16310091",
        "department": "industrial",
        "bsr_multiplier": 0.5,
        "subcategories": {
            "lab_scientific": {"name": "Lab & Scientific Products", "browse_node": "317970011"},
            "janitorial": {"name": "Janitorial & Sanitation Supplies", "browse_node": "317971011"},
        }
    },
    "clothing": {
        "name": "Clothing, Shoes & Jewelry",
        "browse_node": "7141123011",
        "department": "fashion",
        "bsr_multiplier": 0.6,
        "subcategories": {
            "women": {"name": "Women's Fashion", "browse_node": "7147440011"},
            "men": {"name": "Men's Fashion", "browse_node": "7147441011"},
            "jewelry": {"name": "Jewelry", "browse_node": "7192394011"},
        }
    },
    "books": {
        "name": "Books",
        "browse_node": "283155",
        "department": "stripbooks",
        "bsr_multiplier": 1.5,
        "subcategories": {
            "health_fitness": {"name": "Health, Fitness & Dieting", "browse_node": "10"},
            "business": {"name": "Business & Money", "browse_node": "3"},
            "self_help": {"name": "Self-Help", "browse_node": "4736"},
        }
    },
    "cds_vinyl": {
        "name": "CDs & Vinyl",
        "browse_node": "5174",
        "department": "popular",
        "bsr_multiplier": 1.0,
        "subcategories": {}
    },
    "appliances": {
        "name": "Appliances",
        "browse_node": "2619525011",
        "department": "appliances",
        "bsr_multiplier": 0.5,
        "subcategories": {
            "small_appliances": {"name": "Small Appliances", "browse_node": "289913"},
            "parts_accessories": {"name": "Parts & Accessories", "browse_node": "2633116011"},
        }
    },
    "software": {
        "name": "Software",
        "browse_node": "229534",
        "department": "software",
        "bsr_multiplier": 0.4,
        "subcategories": {}
    },
}


def get_category(key):
    """Get a category by key. Returns None if not found."""
    return AMAZON_CATEGORIES.get(key)


def get_all_categories():
    """Get all categories as a dict of {key: {name, browse_node, subcategories}}."""
    result = {}
    for key, cat in AMAZON_CATEGORIES.items():
        subcats = {}
        for sub_key, sub_val in cat.get("subcategories", {}).items():
            subcats[sub_key] = sub_val["name"]
        result[key] = {
            "name": cat["name"],
            "browse_node": cat["browse_node"],
            "subcategories": subcats,
        }
    return result


def get_search_url(category_key, keyword, page=1, subcategory_key=None):
    """
    Build an Amazon search URL for a category + keyword.

    Args:
        category_key: Key from AMAZON_CATEGORIES
        keyword: Search keyword
        page: Page number (1-based)
        subcategory_key: Optional subcategory key

    Returns:
        Full Amazon search URL string
    """
    cat = AMAZON_CATEGORIES.get(category_key)
    if not cat:
        # Fallback: search all of Amazon
        base = "https://www.amazon.com/s"
        params = f"?k={keyword.replace(' ', '+')}&page={page}"
        return base + params

    department = cat["department"]
    browse_node = cat["browse_node"]

    # Use subcategory browse node if specified
    if subcategory_key and subcategory_key in cat.get("subcategories", {}):
        browse_node = cat["subcategories"][subcategory_key]["browse_node"]

    base = "https://www.amazon.com/s"
    params = (
        f"?k={keyword.replace(' ', '+')}"
        f"&i={department}"
        f"&rh=n%3A{browse_node}"
        f"&page={page}"
    )
    return base + params


def get_bsr_multiplier(category_key):
    """Get BSR multiplier for a category (used in sales estimation)."""
    cat = AMAZON_CATEGORIES.get(category_key)
    if cat:
        return cat.get("bsr_multiplier", 1.0)
    return 1.0
