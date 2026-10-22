"""Player-PC account-name defaults; never captured when building packages."""
import getpass
import unicodedata


def clean_account_name(value):
    if not isinstance(value, str): value = ''
    value = unicodedata.normalize('NFC', value.rsplit('\\', 1)[-1].split('@', 1)[0])
    text = ''.join(c if (c.isalpha() or c.isdecimal() or unicodedata.category(c).startswith('M')
                         or c in " ._-'()") else ' ' for c in value)
    text = ' '.join(text.split()).strip(' ._-')
    return text[:32].rstrip() or 'Player'


def default_name():
    try: value = getpass.getuser()
    except (OSError, KeyError, ImportError): value = ''
    return clean_account_name(value)


def chosen_name(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 32 or not value.strip()
            or any(ord(c) < 32 or c in '\x7f"\\' for c in value)):
        raise ValueError('Player name must contain 1..32 characters, without control characters, quotes or backslashes')
    try: value.encode('utf-8')
    except UnicodeError: raise ValueError('Player name contains invalid Unicode') from None
    return value
