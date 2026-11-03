"""mmdb — a MaxMind DB (.mmdb) reader in the standard library alone.

Why our own: the security app answers "where is this address" for every request that reaches an
office and every connection that leaves it, and the office's rule is minimal dependencies. The
format is small and public (https://maxmind.github.io/MaxMind-DB/): a binary search tree over the
address bits, then a data section of self-describing values. This reader maps the file, walks the
tree, decodes the record, and caches answers per network. It reads DB-IP's free "lite" databases
(CC BY 4.0 — the UI credits them) and any other file in the same format.

    db = Reader('/data/geo/dbip-city-lite.mmdb')
    db.get('93.184.216.5')  -> {'city': {...}, 'country': {...}, 'location': {...}, ...} | None
"""
from __future__ import annotations

import ipaddress
import mmap
import struct
import threading

_META_MARKER = b"\xab\xcd\xefMaxMind.com"


class MMDBError(ValueError):
    pass


class Reader:
    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as fh:
            self._buf = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        start = self._buf.rfind(_META_MARKER, max(0, len(self._buf) - 128 * 1024))
        if start < 0:
            raise MMDBError(f"{path}: not a MaxMind DB (no metadata marker)")
        self._meta_start = start + len(_META_MARKER)
        meta, _ = self._decode(self._meta_start, base=self._meta_start)
        self.metadata = meta
        self.node_count = int(meta["node_count"])
        self.record_size = int(meta["record_size"])
        if self.record_size not in (24, 28, 32):
            raise MMDBError(f"{path}: unsupported record size {self.record_size}")
        self.ip_version = int(meta["ip_version"])
        self._node_bytes = self.record_size * 2 // 8
        self._tree_size = self._node_bytes * self.node_count
        self._data_start = self._tree_size + 16
        self._ipv4_start = 0
        if self.ip_version == 6:
            node = 0
            for _ in range(96):
                if node >= self.node_count:
                    break
                node = self._record(node, 0)
            self._ipv4_start = node
        self._lock = threading.Lock()
        self._cache: dict = {}

    # ── tree ─────────────────────────────────────────────────────────────────────────────────────
    def _record(self, node: int, bit: int) -> int:
        off = node * self._node_bytes
        b = self._buf
        if self.record_size == 24:
            o = off + bit * 3
            return (b[o] << 16) | (b[o + 1] << 8) | b[o + 2]
        if self.record_size == 28:
            if bit == 0:
                return ((b[off + 3] & 0xF0) << 20) | (b[off] << 16) | (b[off + 1] << 8) | b[off + 2]
            return ((b[off + 3] & 0x0F) << 24) | (b[off + 4] << 16) | (b[off + 5] << 8) | b[off + 6]
        o = off + bit * 4
        return struct.unpack_from(">I", b, o)[0]

    def lookup(self, ip: str):
        """(record | None, prefix_length) for an address."""
        addr = ipaddress.ip_address(ip)
        packed = addr.packed
        if addr.version == 4:
            if self.ip_version == 4:
                node, bits = 0, 32
            else:
                node, bits = self._ipv4_start, 32
        else:
            if self.ip_version == 4:
                return None, 0
            node, bits = 0, 128
        depth = 0
        for i in range(bits):
            if node >= self.node_count:
                break
            bit = (packed[i >> 3] >> (7 - (i & 7))) & 1
            node = self._record(node, bit)
            depth = i + 1
        if node == self.node_count:
            return None, depth
        if node > self.node_count:
            offset = (node - self.node_count) - 16
            value, _ = self._decode(self._data_start + offset, base=self._data_start)
            return value, depth
        raise MMDBError("invalid tree: ran out of bits inside the tree")

    def get(self, ip: str):
        try:
            key = ipaddress.ip_address(ip)
        except ValueError:
            return None
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None or key in self._cache:
                return hit
        value, _ = self.lookup(str(key))
        with self._lock:
            if len(self._cache) > 50000:
                self._cache.clear()
            self._cache[key] = value
        return value

    # ── data section ─────────────────────────────────────────────────────────────────────────────
    def _size(self, ctrl: int, off: int):
        size = ctrl & 0x1F
        b = self._buf
        if size < 29:
            return size, off
        if size == 29:
            return 29 + b[off], off + 1
        if size == 30:
            return 285 + ((b[off] << 8) | b[off + 1]), off + 2
        return 65821 + ((b[off] << 16) | (b[off + 1] << 8) | b[off + 2]), off + 3

    def _decode(self, off: int, base: int):
        b = self._buf
        ctrl = b[off]
        off += 1
        typ = ctrl >> 5
        if typ == 1:  # pointer: its size bits are part of the address
            ss = (ctrl >> 3) & 0x3
            vvv = ctrl & 0x7
            if ss == 0:
                ptr = (vvv << 8) | b[off]
                off += 1
            elif ss == 1:
                ptr = ((vvv << 16) | (b[off] << 8) | b[off + 1]) + 2048
                off += 2
            elif ss == 2:
                ptr = ((vvv << 24) | (b[off] << 16) | (b[off + 1] << 8) | b[off + 2]) + 526336
                off += 3
            else:
                ptr = struct.unpack_from(">I", b, off)[0]
                off += 4
            value, _ = self._decode(base + ptr, base)
            return value, off
        if typ == 0:  # extended type
            typ = 7 + b[off]
            off += 1
        size, off = self._size(ctrl, off)
        if typ == 2:
            return bytes(b[off:off + size]).decode("utf-8"), off + size
        if typ == 3:
            return struct.unpack_from(">d", b, off)[0], off + 8
        if typ == 4:
            return bytes(b[off:off + size]), off + size
        if typ in (5, 6, 9, 10):
            return int.from_bytes(b[off:off + size], "big"), off + size
        if typ == 8:
            raw = int.from_bytes(b[off:off + size], "big")
            if size == 4 and raw & 0x80000000:
                raw -= 1 << 32
            return raw, off + size
        if typ == 7:
            out = {}
            for _ in range(size):
                k, off = self._decode(off, base)
                v, off = self._decode(off, base)
                out[k] = v
            return out, off
        if typ == 11:
            arr = []
            for _ in range(size):
                v, off = self._decode(off, base)
                arr.append(v)
            return arr, off
        if typ == 14:
            return bool(size), off
        if typ == 15:
            return struct.unpack_from(">f", b, off)[0], off + 4
        if typ in (12, 13):
            return None, off
        raise MMDBError(f"unknown data type {typ} at {off}")

    def close(self):
        try:
            self._buf.close()
        except Exception:
            pass
