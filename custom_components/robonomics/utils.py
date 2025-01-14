from substrateinterface import Keypair, KeypairType
from robonomicsinterface import Account
from typing import Union
import random, string
import functools
import typing as tp
import asyncio
import functools
import logging
import os
import random
import string
import tempfile
import time
import typing as tp
from typing import Union
import shutil

import ipfshttpclient2
from homeassistant.components.notify.const import DOMAIN as NOTIFY_DOMAIN
from homeassistant.components.notify.const import SERVICE_PERSISTENT_NOTIFICATION
from homeassistant.core import HomeAssistant
import time
import json

_LOGGER = logging.getLogger(__name__)


async def create_notification(hass: HomeAssistant, service_data: tp.Dict[str, str]) -> None:
    """Create HomeAssistant notification.

    :param hass: HomeAssistant instance
    :param service_data: Message for notification
    """

    await hass.services.async_call(
        domain=NOTIFY_DOMAIN,
        service=SERVICE_PERSISTENT_NOTIFICATION,
        service_data=service_data,
    )


def encrypt_message(message: Union[bytes, str], sender_keypair: Keypair, recipient_public_key: bytes) -> str:
    """Encrypt message with sender private key and recipient public key

    :param message: Message to encrypt
    :param sender_keypair: Sender account Keypair
    :param recipient_public_key: Recipient public key

    :return: encrypted message
    """

    encrypted = sender_keypair.encrypt_message(message, recipient_public_key)
    return f"0x{encrypted.hex()}"


def decrypt_message(encrypted_message: str, sender_public_key: bytes, recipient_keypair: Keypair) -> str:
    """Decrypt message with recepient private key and sender puplic key

    :param encrypted_message: Message to decrypt
    :param sender_public_key: Sender public key
    :param recipient_keypair: Recepient account keypair

    :return: Decrypted message
    """

    if encrypted_message[:2] == "0x":
        encrypted_message = encrypted_message[2:]
    bytes_encrypted = bytes.fromhex(encrypted_message)

    return recipient_keypair.decrypt_message(bytes_encrypted, sender_public_key)


def encrypt_for_devices(data: str, sender_kp: Keypair, devices: tp.List[str]) -> str:
    """
    Encrypt data for random generated private key, then encrypt this key for device from the list

    :param data: Data to encrypt
    :param sender_kp: ED25519 account keypair that encrypts the data
    :param devices: List of ss58 ED25519 addresses

    :return: JSON string consists of encrypted data and a key encrypted for all accounts in the subscription
    """
    try:
        random_seed = Keypair.generate_mnemonic()
        random_acc = Account(random_seed, crypto_type=KeypairType.ED25519)
        encrypted_data = encrypt_message(str(data), sender_kp, random_acc.keypair.public_key)
        encrypted_keys = {}
        _LOGGER.debug(f"Encrypt states for following devices: {devices}")
        for device in devices:
            try:
                receiver_kp = Keypair(ss58_address=device, crypto_type=KeypairType.ED25519)
                encrypted_key = encrypt_message(random_seed, sender_kp, receiver_kp.public_key)
            except Exception as e:
                _LOGGER.warning(f"Faild to encrypt key for: {device} with error: {e}")
            encrypted_keys[device] = encrypted_key
        encrypted_keys["data"] = encrypted_data
        data_final = json.dumps(encrypted_keys)
        return data_final
    except Exception as e:
        _LOGGER.error(f"Exception in encrypt for devices: {e}")


def decrypt_message_devices(data: str, sender_public_key: bytes, recipient_keypair: Keypair) -> str:
    """Decrypt message that was encrypted fo devices
    
    :param data: Ancrypted data
    :param sender_public_key: Sender address
    :param recipient_keypair: Recepient account keypair

    :return: Decrypted message
    """
    try:
        _LOGGER.debug(f"Start decrypt for device {recipient_keypair.ss58_address}")
        data_json = json.loads(data)
        if recipient_keypair.ss58_address in data_json:
            decrypted_seed = decrypt_message(data_json[recipient_keypair.ss58_address], sender_public_key, recipient_keypair)
            decrypted_acc = Account(decrypted_seed.decode("utf-8"), crypto_type=KeypairType.ED25519)
            decrypted_data = decrypt_message(data_json["data"], sender_public_key, decrypted_acc.keypair)
            return decrypted_data
        else:
            _LOGGER.error(f"Error in decrypt for devices: account is not in devices")
    except Exception as e:
        _LOGGER.error(f"Exception in decrypt for devices: {e}")



def str2bool(v):
    return v.lower() in ("on", "true", "t", "1", "y", "yes", "yeah")


def generate_pass(length: int) -> str:
    """Generate random low letter string with the given length

    :param lenght: Password length

    :return: Generated password
    """

    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def to_thread(func: tp.Callable) -> tp.Coroutine:
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    return wrapper


@to_thread
def get_hash(filename: str) -> tp.Optional[str]:
    """Getting file's IPFS hash

    :param filename: Path to the backup file

    :return: Hash of the file or None
    """

    try:
        with ipfshttpclient2.connect() as client:
            ipfs_hash_local = client.add(filename, pin=False)["Hash"]
    except Exception as e:
        _LOGGER.error(f"Exception in get_hash with local node: {e}")
        ipfs_hash_local = None
    return ipfs_hash_local


def create_encrypted_picture(data: bytes, number_of_picture: int, dirname: str, sender_seed: tp.Optional[str] = None, receiver_address: tp.Optional[str] = None) -> str:
    sender_acc = Account(seed=sender_seed, crypto_type=KeypairType.ED25519)
    sender_kp = sender_acc.keypair
    receiver_kp = Keypair(ss58_address=receiver_address, crypto_type=KeypairType.ED25519)
    encrypted_data = encrypt_message(data, sender_kp, receiver_kp.public_key)
    picture_path = f"{dirname}/picture{number_of_picture}"
    with open(picture_path, "w") as f:
        f.write(encrypted_data)
    _LOGGER.debug(f"Created encrypted picture: {picture_path}")
    return picture_path


def write_data_to_temp_file(data: tp.Union[str, bytes], config: bool = False, filename: str = None) -> str:
    """
    Create file and store data in it

    :param data: data, which to be written to the file
    :param config: is file fo config (True) or for telemetry (False)
    :param filename: Name of the file if not config or z2m backup

    :return: path to created file
    """
    dirname = tempfile.gettempdir()
    if filename is not None:
        filepath = f"{dirname}/{filename}"
        if type(data) == str:
            with open(filepath, "w") as f:
                f.write(data)
        else:
            with open(filepath, "wb") as f:
                f.write(data)
    else:
        if type(data) == str:
            if config:
                filepath = f"{dirname}/config_encrypted-{time.time()}"
            else:
                filepath = f"{dirname}/data-{time.time()}"
            with open(filepath, "w") as f:
                f.write(data)
        else:
            filepath = f"{dirname}/z2m-backup.zip"
            with open(filepath, "wb") as f:
                f.write(data)
    return filepath


def create_temp_dir_and_copy_files(dirname: str, files: tp.List[str], sender_seed: tp.Optional[str] = None, receiver_address: tp.Optional[str] = None) -> str:
    """
    Create directory in tepmoral directory and copy there files

    :param dirname: the name of the directory to create
    :param files: list of file pathes to copy

    :return: path to the created directory    
    """
    try:
        temp_dirname = tempfile.gettempdir()
        dirpath = f"{temp_dirname}/{dirname}"
        if os.path.exists(dirpath):
            dirpath += str(random.randint(1, 100))
        os.mkdir(dirpath)
        for filepath in files:
            filename = filepath.split("/")[-1]
            if sender_seed and receiver_address:
                with open(filepath, "r") as f:
                    data = f.read()
                sender_acc = Account(seed=sender_seed, crypto_type=KeypairType.ED25519)
                sender_kp = sender_acc.keypair
                receiver_kp = Keypair(ss58_address=receiver_address, crypto_type=KeypairType.ED25519)
                encrypted_data = encrypt_message(data, sender_kp, receiver_kp.public_key)
                with open(f"{dirpath}/{filename}", "w") as f:
                    f.write(encrypted_data)
            else:
                shutil.copyfile(filepath, f"{dirpath}/{filename}")
        return dirpath
    except Exception as e:
        _LOGGER.error(f"Exception in create temp dir: {e}")


def delete_temp_dir(dirpath: str) -> None:
    """
    Delete temporary directory

    :param dirpath: the path to the directory
    """
    shutil.rmtree(dirpath)


def delete_temp_file(filename: str) -> None:
    """
    Delete temporary file

    :param filename: the name of the file to delete
    """
    os.remove(filename)
