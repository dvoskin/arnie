"""
Stripe billing helpers — checkout sessions and customer portal.
"""
import os
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

PRICE_ID   = os.getenv("STRIPE_PRICE_ID", "")
BOT_URL    = "tg://resolve?domain=Arnie_1026_Bot"
SITE_URL   = "https://tryarnie.com"


def create_checkout_session(telegram_id: str) -> str:
    """Create a Stripe Checkout session and return the hosted URL."""
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": PRICE_ID, "quantity": 1}],
        metadata={"telegram_id": telegram_id},
        success_url=BOT_URL + "?start=paid",
        cancel_url=SITE_URL,
        allow_promotion_codes=True,
    )
    return session.url


def create_billing_portal(stripe_customer_id: str) -> str:
    """Return a Stripe Customer Portal URL so users can manage/cancel."""
    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=BOT_URL,
    )
    return session.url
