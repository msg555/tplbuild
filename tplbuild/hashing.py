import hashlib
import json

# The default hashing algorithm used by tplbuild.
HASHER = hashlib.sha256


class HashWriter:
    """
    File-like writable object that passed all writes through to the supplied
    hasher. It will automatically encode str data using the supplied encoding.
    """

    def __init__(self, hsh, *, encoding="utf-8") -> None:
        self.hsh = hsh
        self.encoding = encoding

    def write(self, data):
        """Write data to the underlying hasher"""
        if isinstance(data, bytes):
            self.hsh.update(data)
        else:
            self.hsh.update(data.encode(self.encoding))


def json_hash(data) -> str:
    """
    Generate a crytographic hash of JSON-able data. Returns the hex digest.
    """
    hsh = HASHER()
    json.dump(data, HashWriter(hsh), sort_keys=True)  # type: ignore
    return hsh.hexdigest()
