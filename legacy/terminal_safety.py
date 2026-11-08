"""Make untrusted source/model text visible without executing terminal controls."""
import unicodedata


def terminal_text(value):
    return ''.join(c if c in '\n\t' or (ord(c) >= 32 and ord(c) != 127
                                       and not 0x80 <= ord(c) <= 0x9f
                                       and unicodedata.category(c) != 'Cf')
                   else (f'\\u{ord(c):04x}' if ord(c) > 255 else f'\\x{ord(c):02x}')
                   for c in str(value))
