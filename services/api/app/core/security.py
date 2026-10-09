"""
安全工具模块。

提供密码哈希与校验、JWT 令牌签发与解析、AES-256-CBC 加解密功能。
密码哈希使用 bcrypt 库；JWT 使用 python-jose（HS256）；AES 使用 cryptography。
"""

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from jose import JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。

    Args:
        password: 明文密码。

    Returns:
        str: bcrypt 哈希后的字符串。
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。

    Args:
        plain: 明文密码。
        hashed: 存储的哈希字符串。

    Returns:
        bool: 匹配返回 True，否则 False。
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict[str, Any], expires_minutes: int | None = None) -> str:
    """创建 JWT 访问令牌。

    Args:
        data: 要编码到令牌中的载荷数据。
        expires_minutes: 过期分钟数，为空时使用配置默认值。

    Returns:
        str: 编码后的 JWT 字符串。
    """
    to_encode = data.copy()
    expire_minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """创建 JWT 刷新令牌。

    Args:
        data: 要编码到令牌中的载荷数据。

    Returns:
        str: 编码后的刷新令牌字符串。
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """解析并校验 JWT 令牌。

    Args:
        token: JWT 字符串。

    Returns:
        dict: 解码后的载荷字典。

    Raises:
        JWTError: 令牌无效或已过期时抛出。
    """
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    return payload


def _get_aes_key() -> bytes:
    """从配置中获取 AES 密钥（支持 16/24/32 字节，对应 AES-128/192/256）。

    若配置的 AES_SECRET_KEY 为 32 字节则使用 AES-256-CBC；
    16 字节则使用 AES-128-CBC，依此类推。

    Returns:
        bytes: 合法长度的密钥。

    Raises:
        ValueError: 密钥长度不合法（非 16/24/32 字节）时抛出。
    """
    key = bytes.fromhex(settings.AES_SECRET_KEY)
    if len(key) not in (16, 24, 32):
        raise ValueError("AES_SECRET_KEY 必须为 16/24/32 字节（32/48/64 个十六进制字符）")
    return key


def aes_encrypt(plaintext: str) -> str:
    """使用 AES-256-CBC 加密文本，返回 base64（IV 前置）。

    Args:
        plaintext: 待加密的明文字符串。

    Returns:
        str: base64 编码的 IV + 密文。

    Raises:
        ValueError: 密钥不合法时抛出。
    """
    key = _get_aes_key()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()

    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(iv + ciphertext).decode("utf-8")


def aes_decrypt(ciphertext: str) -> str:
    """解密 AES-256-CBC 密文（IV 前置的 base64）。

    Args:
        ciphertext: base64 编码的 IV + 密文。

    Returns:
        str: 解密后的明文字符串。

    Raises:
        ValueError: 密钥或密文格式不合法时抛出。
    """
    key = _get_aes_key()
    raw = base64.b64decode(ciphertext)
    iv, encrypted = raw[:16], raw[16:]

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode("utf-8")
