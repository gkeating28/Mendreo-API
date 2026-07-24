from inapppy import GooglePlayValidator, AppStoreValidator, InAppPyValidationError

from ..utils import Api, DateUtils, Exception as CustomException


def google_validator(receipt, signature, price, raise_exceptions=True):
    from rest_framework import status

    bundle_id = Api.BUNDLE_ID_ANDROID
    if ".dev" in bundle_id or ".staging" in bundle_id:
        return True

    api_key = Api.GOOGLE_API_KEY
    validator = GooglePlayValidator(bundle_id, api_key)

    try:
        # receipt means `androidData` in result of purchase
        # signature means `signatureAndroid` in result of purchase
        validation_result = validator.validate(receipt, signature)

        # todo check price and frequency match expected
        return validation_result
    except InAppPyValidationError as ex:
        # handle validation error
        response_from_google = ex.raw_response  # contains actual response from Google play Store service.
        print(f"Google Error: {response_from_google}, receipt: {receipt}")
        if raise_exceptions:
            CustomException.raise_error("Error validating payment", status.HTTP_400_BAD_REQUEST)
        return ex


def apple_validator(receipt, price, raise_exceptions=True):
    from rest_framework import status

    bundle_id = Api.BUNDLE_ID_IOS
    if ".dev" in bundle_id or ".staging" in bundle_id:
        return True

    # if True, automatically query sandbox endpoint if validation fails on production endpoint
    auto_retry_wrong_env_request = True
    validator = AppStoreValidator(bundle_id, auto_retry_wrong_env_request=auto_retry_wrong_env_request)

    try:
        exclude_old_transactions = False  # if True, include only the latest renewal transaction
        validation_result = validator.validate(
            receipt,
            Api.APPLE_IN_APP_SHARED_SECRET,
            exclude_old_transactions=exclude_old_transactions
        )

        receipt = validation_result["receipt"]
        in_app_purchase = receipt["in_app"][-1]
        latest_receipt_info = validation_result["latest_receipt_info"][-1]
        expiry_date_ms = latest_receipt_info["expires_date_ms"]
        expiry_date = DateUtils.from_timestamp(float(expiry_date_ms) / 1000.0)

        if price.apple_id != in_app_purchase["product_id"]:
            CustomException.raise_error(
                "Error validating payment receipt, please contact support",
                status.HTTP_400_BAD_REQUEST
            )

        if DateUtils.date_in_past(expiry_date.date()):
            CustomException.raise_error(
                "subscription has expired",
                status.HTTP_400_BAD_REQUEST
            )

        return validation_result
    except InAppPyValidationError as ex:
        # handle validation error
        response_from_apple = ex.raw_response  # contains actual response from AppStore service.
        print(f"Apple Error: {response_from_apple}, receipt: {receipt}")
        if raise_exceptions:
            CustomException.raise_error("Error validating payment", status.HTTP_400_BAD_REQUEST)
        return ex
    except Exception as e:
        # handle validation error
        print(f"General Error: {e}")
        if raise_exceptions:
            CustomException.raise_error("Error validating payment", status.HTTP_400_BAD_REQUEST)
        return e
