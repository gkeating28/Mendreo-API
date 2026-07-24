
import phonenumbers


def is_valid(number):
    if not number:
        return False

    try:
        phone = phonenumbers.parse(number, None)
        if not phonenumbers.is_valid_number(phone):
            return False
    except Exception as e:
        return False

    return True
