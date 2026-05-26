import stripe, json

from ..utils import Api

stripe.api_key = Api.STRIPE_SECRET_KEY
stripe.api_version = '2023-10-16'


def get_payment_intent(payment_intent_id):
    return stripe.PaymentIntent.retrieve(
        payment_intent_id,
        expand=['invoice.subscription']
    )


def get_subscription(subscription_id):
    return stripe.Subscription.retrieve(subscription_id)


def requires_user_action(payment_intent):
    return payment_intent.status in ["requires_action", "requires_source_action"] and payment_intent.next_action.type == "use_stripe_sdk"


def payment_intent_paid(payment_intent):
    return payment_intent.status == "succeeded"


def create(consumer, payment_method_id, package):

    product = stripe.Product.create(
        name=package.title
    )

    price = package.price
    interval = price.frequency.replace("ly", "")

    if not consumer.stripe_customer_id:
        user = consumer.user
        customer = stripe.Customer.create(
            name=user.full_name,
            email=consumer.user.email,
        )
        consumer.stripe_customer_id = customer.id
        consumer.save()

    payment_method = stripe.PaymentMethod.attach(
        payment_method_id,
        customer=consumer.stripe_customer_id,
    )

    subscription = stripe.Subscription.create(
        customer=consumer.stripe_customer_id,
        default_payment_method=payment_method.id,
        items=[
            {
                "price_data": {
                    "currency": price.currency.code,
                    "product": product.id,
                    "recurring": {
                        "interval": interval,
                        "interval_count": 1
                    },
                    "unit_amount": price.amount
                }
            }
        ],
        collection_method="charge_automatically",
        payment_behavior="default_incomplete",
        payment_settings={
            "save_default_payment_method": "on_subscription"
        },
        expand=['latest_invoice.payment_intent'],
    )

    return subscription


def cancel(subscription_id):
    cancellation = stripe.Subscription.delete(
        subscription_id,
    )

    cancellation_data = json.loads(str(cancellation))

    return cancellation_data
