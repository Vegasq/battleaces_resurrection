"""Client release policy, separate from the deterministic game protocol."""
CLIENT_REVISION = 1
DEFAULT_UPDATE_MESSAGE = ('Client update required (0.4.0).\n'
                          'Download the latest installer from GitHub Releases.')
UPDATE_PREFIX = 'BA_UPDATE_REQUIRED/'


def validate_policy(minimum, message):
    if type(minimum) is not int or not 0 <= minimum <= 0xffffffff:
        raise ValueError('minimum_client_revision must be an integer in0..4294967295')
    if (not isinstance(message, str) or not 1 <= len(message) <= 160
            or any(not (32 <= ord(char) <= 126 or char == '\n') for char in message)):
        raise ValueError('client_update_message must contain1..160 plain ASCII characters or newlines')
    return minimum, message


def rejection(minimum, message):
    validate_policy(minimum, message)
    return f'{UPDATE_PREFIX}{minimum}/{message}'
