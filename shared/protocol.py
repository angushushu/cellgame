"""Message codec: JSON + base64-encoded NumPy arrays (spec section 3).

Every message on the wire is a JSON object:
    {"type": "<msg>", "payload": {...}}
NumPy arrays inside payloads are packed as
    {"__ndarray__": {"dtype": "...", "shape": [...], "data": "<base64>"}}
and unpacked back on decode.
"""
import base64
import json
import math

import numpy as np
from .contract import MAX_ARRAY_BYTES, MAX_MESSAGE_BYTES


class ProtocolError(ValueError):
    """Malformed transport data; callers can reject it without mutating state."""


def _numeric_dtype(dtype):
    if dtype.fields is not None:
        if not dtype.names or len(dtype.names) > 64:
            raise ProtocolError("invalid record fields")
        offset = 0
        for name in dtype.names:
            field = dtype.fields[name][0]
            if dtype.fields[name][1] != offset:
                raise ProtocolError("padded record arrays are not supported")
            if not name or field.fields is not None or field.subdtype is not None:
                raise ProtocolError("only flat scalar record fields are supported")
            _numeric_dtype(field)
            offset += field.itemsize
        if offset != dtype.itemsize:
            raise ProtocolError("padded record arrays are not supported")
    elif not ((dtype.kind in "iu" and dtype.itemsize in (1, 2, 4, 8)) or
              (dtype.kind == "b" and dtype.itemsize == 1) or
              (dtype.kind == "f" and dtype.itemsize in (4, 8))):
        raise ProtocolError("only fixed-width numeric array types are supported")
    if dtype.hasobject:
        raise ProtocolError("object arrays are not supported")
    return dtype.newbyteorder('<')


def array_to_b64(arr):
    arr = np.asarray(arr)
    dtype = _numeric_dtype(arr.dtype)
    if arr.ndim > 4 or arr.nbytes > MAX_ARRAY_BYTES:
        raise ProtocolError("array exceeds transport limits")
    arr = np.ascontiguousarray(arr.astype(dtype, copy=False)).reshape(arr.shape)
    out = {
        "dtype": str(arr.dtype),
        "shape": list(arr.shape),
        "data": base64.b64encode(arr.tobytes()).decode("ascii"),
        "byteorder": "little",
        "order": "C",
    }
    # str() of a structured dtype does not parse back; keep descr.
    if arr.dtype.fields is not None:
        out["descr"] = [[str(name), str(t)] for name, t in arr.dtype.descr]
    return out


def b64_to_array(obj):
    try:
        if not isinstance(obj, dict) or obj.get("byteorder", "little") != "little" or obj.get("order", "C") != "C":
            raise ProtocolError("unsupported array encoding")
        shape, data = obj["shape"], obj["data"]
        if (not isinstance(shape, list) or len(shape) > 4 or
                any(type(n) is not int or n < 0 for n in shape)):
            raise ProtocolError("invalid array shape")
        if "descr" in obj:
            descr = obj["descr"]
            if (not isinstance(descr, list) or not 1 <= len(descr) <= 64 or
                    any(not isinstance(f, list) or len(f) != 2 or not all(isinstance(v, str) for v in f) for f in descr)):
                raise ProtocolError("invalid record descriptor")
            dt = np.dtype([tuple(f) for f in descr])
        else:
            dt = np.dtype(obj["dtype"])
        # An explicitly big-endian descriptor conflicts with the v2 wire contract.
        fields = [dt.fields[n][0] for n in dt.names] if dt.names else [dt]
        if any(field.byteorder == '>' for field in fields):
            raise ProtocolError("wire arrays must be little-endian")
        dt = _numeric_dtype(dt)
        size = math.prod(shape) * dt.itemsize
        if size > MAX_ARRAY_BYTES or not isinstance(data, str) or len(data) > ((MAX_ARRAY_BYTES + 2) // 3) * 4:
            raise ProtocolError("array exceeds transport limits")
        raw = base64.b64decode(data, validate=True)
        if len(raw) != size:
            raise ProtocolError("array byte count does not match shape")
        return np.frombuffer(raw, dtype=dt).reshape(shape)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ProtocolError(str(exc)) from exc


def _pack(obj):
    if isinstance(obj, np.ndarray):
        return {"__ndarray__": array_to_b64(obj)}
    if isinstance(obj, dict):
        return {k: _pack(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_pack(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def _unpack(obj):
    if isinstance(obj, dict):
        if "__ndarray__" in obj:
            if set(obj) != {"__ndarray__"}:
                raise ProtocolError("ambiguous reserved array wrapper")
            return b64_to_array(obj["__ndarray__"])
        return {k: _unpack(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unpack(v) for v in obj]
    return obj


def encode_msg(msg_type, **payload):
    if not isinstance(msg_type, str) or not 1 <= len(msg_type) <= 64:
        raise ProtocolError("invalid message type")
    result = json.dumps({"type": msg_type, "payload": _pack(payload)}, allow_nan=False)
    if len(result.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message too large")
    return result


def decode_msg(raw):
    if not isinstance(raw, (str, bytes)) or len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError("invalid or oversized message")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    elif len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message too large")
    def reject_constant(value):
        raise ProtocolError("non-finite JSON number")
    msg = json.loads(raw, parse_constant=reject_constant)
    if (not isinstance(msg, dict) or not isinstance(msg.get("type"), str) or
            not 1 <= len(msg["type"]) <= 64 or not isinstance(msg.get("payload", {}), dict)):
        raise ProtocolError("invalid message envelope")
    return msg["type"], _unpack(msg.get("payload", {}))


def integer_rows(data, width, max_rows, *, allow_single=False):
    """Validate an action table before narrowing any values to fixed-width fields."""
    if isinstance(data, (list, tuple)):
        single = allow_single and data and not isinstance(data[0], (list, tuple, np.ndarray))
        if single:
            values = data
        else:
            if any(not isinstance(row, (list, tuple, np.ndarray)) or np.ndim(row) != 1 for row in data):
                raise ProtocolError("actions must be a table of rows")
            values = [v for row in data for v in row]
        if any(not isinstance(v, (int, np.integer)) or isinstance(v, (bool, np.bool_)) for v in values):
            raise ProtocolError("action fields must be integers, not booleans or decimals")
    try:
        arr = np.asarray(data)
    except (ValueError, TypeError) as exc:
        raise ProtocolError("actions must be an integer table") from exc
    if arr.size == 0:
        if arr.ndim not in (1, 2) or (arr.ndim == 2 and arr.shape[1] != width):
            raise ProtocolError("invalid empty action table")
        return np.empty((0, width), dtype=np.int64)
    if allow_single and arr.ndim == 1 and len(arr) == width:
        arr = arr.reshape(1, width)
    if arr.ndim != 2 or arr.shape[1] != width or len(arr) > max_rows or arr.dtype.kind not in "iu":
        raise ProtocolError(f"actions must be an (n, {width}) integer table")
    if arr.dtype.kind == 'u' and arr.max() > np.iinfo(np.int64).max:
        raise ProtocolError("integer out of range")
    return arr.astype(np.int64, copy=False)
