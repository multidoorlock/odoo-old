"""Build fixed-width MASAV payment files without depending on Odoo.

The layout implemented here follows the MASAV payment-file specification:
128-byte records followed by CRLF, with K/1/5 header, payment and total
records.  This module deliberately accepts plain Python values only so the
file-format logic can be reused and changed independently of Odoo models.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable


RECORD_LENGTH = 128
RECORD_SEPARATOR = b'\r\n'
_HEBREW = 'אבגדהוזחטיךכלםמןנסעףפץצקרשת'
_HEBREW_CODE_B = {letter: bytes([0x80 + index]) for index, letter in enumerate(_HEBREW)}
_HEBREW_CODE_A = {
    letter: bytes([0x26 if index == 0 else 0x40 + index])
    for index, letter in enumerate(_HEBREW)
}


class MasavValidationError(ValueError):
    """Raised when a value cannot be represented in the MASAV layout."""


@dataclass(frozen=True)
class MasavPayment:
    bank_code: str
    branch_code: str
    account_number: str
    beneficiary_id: str
    beneficiary_name: str
    amount: Decimal
    reference: str
    period_from: date
    period_to: date
    transaction_type: str = '006'


@dataclass(frozen=True)
class MasavFile:
    institution_number: str
    sender_number: str
    institution_name: str
    payment_date: date
    creation_date: date
    payments: Iterable[MasavPayment]
    serial_number: int = 1
    hebrew_code: str = 'b'


def _digits(value, length, field_name, *, pad=True):
    text = str(value or '').strip()
    if not text or not text.isascii() or not text.isdigit():
        raise MasavValidationError(f'{field_name} must contain digits only')
    if len(text) > length:
        raise MasavValidationError(f'{field_name} is longer than {length} digits')
    return (text.zfill(length) if pad else text).encode('ascii')


def _encode_text(value, hebrew_code):
    mapping = _HEBREW_CODE_B if hebrew_code == 'b' else _HEBREW_CODE_A
    if hebrew_code not in ('a', 'b'):
        raise MasavValidationError('hebrew_code must be either "a" or "b"')
    result = bytearray()
    for character in str(value or ''):
        if character in mapping:
            result.extend(mapping[character])
        elif 0x20 <= ord(character) <= 0x7E:
            result.append(ord(character))
        else:
            raise MasavValidationError(
                f'Unsupported character U+{ord(character):04X} in text field')
    return bytes(result)


def _text(value, length, field_name, hebrew_code, *, align='left', visual=False):
    value = str(value or '').strip()
    if visual and any(character in _HEBREW for character in value):
        value = value[::-1]
    encoded = _encode_text(value, hebrew_code)
    if len(encoded) > length:
        raise MasavValidationError(f'{field_name} is longer than {length} characters')
    return encoded.rjust(length, b' ') if align == 'right' else encoded.ljust(length, b' ')


def _date(value, include_day=True):
    if not isinstance(value, date):
        raise MasavValidationError('MASAV dates must be datetime.date values')
    return value.strftime('%y%m%d' if include_day else '%y%m').encode('ascii')


def _amount(value, length, field_name):
    amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if amount <= 0:
        raise MasavValidationError(f'{field_name} must be greater than zero')
    agorot = int(amount * 100)
    return _digits(agorot, length, field_name)


def _record(parts):
    record = b''.join(parts)
    if len(record) != RECORD_LENGTH:
        raise AssertionError(f'MASAV record is {len(record)} bytes instead of 128')
    return record + RECORD_SEPARATOR


def _header(spec):
    return _record([
        b'K',
        _digits(spec.institution_number, 8, 'institution_number'),
        b'00',
        _date(spec.payment_date),
        b'0',
        _digits(spec.serial_number, 3, 'serial_number'),
        b'0',
        _date(spec.creation_date),
        _digits(spec.sender_number, 5, 'sender_number'),
        b'000000',
        _text(spec.institution_name, 30, 'institution_name', spec.hebrew_code,
              align='right', visual=True),
        b' ' * 56,
        b'KOT',
    ])


def _payment_record(spec, payment):
    period = _date(payment.period_from, include_day=False) + _date(
        payment.period_to, include_day=False)
    return _record([
        b'1',
        _digits(spec.institution_number, 8, 'institution_number'),
        b'00',
        b'000000',
        _digits(payment.bank_code, 2, 'bank_code'),
        _digits(payment.branch_code, 3, 'branch_code'),
        b'0000',
        _digits(payment.account_number, 9, 'account_number'),
        b'0',
        _digits(payment.beneficiary_id, 9, 'beneficiary_id'),
        _text(payment.beneficiary_name, 16, 'beneficiary_name', spec.hebrew_code,
              visual=True),
        _amount(payment.amount, 13, 'amount'),
        _digits(payment.reference, 20, 'reference'),
        period,
        b'000',
        _digits(payment.transaction_type, 3, 'transaction_type'),
        b'0' * 18,
        b'  ',
    ])


def _total(spec, payment_count, total_amount):
    return _record([
        b'5',
        _digits(spec.institution_number, 8, 'institution_number'),
        b'00',
        _date(spec.payment_date),
        b'0',
        _digits(spec.serial_number, 3, 'serial_number'),
        _amount(total_amount, 15, 'total_amount'),
        b'0' * 15,
        _digits(payment_count, 7, 'payment_count'),
        b'0' * 7,
        b' ' * 63,
    ])


def build_masav_file(spec):
    """Return a complete MASAV payment file as bytes."""
    if not isinstance(spec, MasavFile):
        raise TypeError('spec must be a MasavFile instance')
    payments = tuple(spec.payments)
    if not payments:
        raise MasavValidationError('At least one payment is required')
    total = sum((Decimal(str(payment.amount)) for payment in payments), Decimal('0'))
    records = [_header(spec)]
    records.extend(_payment_record(spec, payment) for payment in payments)
    records.append(_total(spec, len(payments), total))
    return b''.join(records)
