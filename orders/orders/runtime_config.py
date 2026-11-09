"""Local Django secret key configuration; no .env files are loaded."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key


def secret_key(base_dir):
    configured = os.environ.get('DJANGO_SECRET_KEY', '').strip()
    if configured:
        return configured
    # Stable local key survives server restarts and is excluded from version control.
    path = Path(base_dir) / '.django-secret-key'
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        value = path.read_text(encoding='utf-8').strip()
        if not value:
            raise ImproperlyConfigured('Локальный ключ пуст. Задайте DJANGO_SECRET_KEY.')
        return value
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        value = get_random_secret_key()
        stream.write(value)
    return value
