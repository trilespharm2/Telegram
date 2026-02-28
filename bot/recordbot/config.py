import os

RECORDBOT_PRICE_2H = os.getenv("RECORDBOT_PRICE_2H", "")
RECORDBOT_PRICE_5H = os.getenv("RECORDBOT_PRICE_5H", "")
RECORDBOT_PRICE_20H = os.getenv("RECORDBOT_PRICE_20H", "")

RECORDBOT_CHANNEL_ID = os.getenv("RECORDBOT_CHANNEL_ID", "")

RECORDBOT_PLANS = {
    "rb_plan_2h": {
        "label": "2 Hours — $5",
        "price_id_env": "RECORDBOT_PRICE_2H",
        "hours": 2,
        "amount_display": "$5",
    },
    "rb_plan_5h": {
        "label": "5 Hours — $10",
        "price_id_env": "RECORDBOT_PRICE_5H",
        "hours": 5,
        "amount_display": "$10",
    },
    "rb_plan_20h": {
        "label": "20 Hours — $20",
        "price_id_env": "RECORDBOT_PRICE_20H",
        "hours": 20,
        "amount_display": "$20",
    },
}

def get_price_id(plan_key):
    plan = RECORDBOT_PLANS.get(plan_key)
    if not plan:
        return None
    return os.getenv(plan["price_id_env"], "")
