from cryptography.fernet import Fernet

from . import config


def _load_or_create_key() -> bytes:
    if config.MASTER_KEY_ENV:
        return config.MASTER_KEY_ENV.encode()

    if config.MASTER_KEY_PATH.exists():
        return config.MASTER_KEY_PATH.read_bytes()

    key = Fernet.generate_key()
    config.MASTER_KEY_PATH.write_bytes(key)
    config.MASTER_KEY_PATH.chmod(0o600)
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None or plaintext == "":
        return None
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None or ciphertext == "":
        return None
    return _fernet.decrypt(ciphertext.encode()).decode()
