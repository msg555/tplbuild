import hashlib
import json

HASHER = hashlib.sha256


class HashWriter:
    def __init__(self, hsh) -> None:
        self.hsh = hsh

    def write(self, data):
        self.hsh.update(data.encode("utf-8"))


def json_hash(data) -> str:
    """
    Generate a crytographic hash of JSON-able data. Returns the hex digest.
    """
    hsh = HASHER()
    json.dump(data, HashWriter(hsh), sort_keys=True)
    return hsh.hexdigest()
