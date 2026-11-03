"""Turn an mlx-lm LoRA adapter file into the PEFT layout the judge server loads, on bytes.

mlx-lm stores `<module>.lora_a` as (in, r) and `.lora_b` as (r, out); PEFT stores
`base_model.model.<module>.lora_A.weight` as (r, in) and `lora_B.weight` as (out, r). Elements move
as raw bytes, so bf16 and f32 tensors survive exactly and no `safetensors` install is needed.
"""

import json
import struct
from typing import Any

import numpy as np

PEFT_PREFIX = "base_model.model."
SIDES = {"lora_a": "lora_A", "lora_b": "lora_B"}
WIDTH = {"F32": 4, "F16": 2, "BF16": 2}
_LENGTH = struct.Struct("<Q")
Entry = dict[str, Any]  # one tensor's safetensors header record: dtype, shape, data_offsets


class AdapterFormatError(ValueError):
    """The file is not a safetensors file of mlx-lm LoRA tensors; the message says what is wrong."""


def _read(blob: bytes) -> tuple[dict[str, Entry], memoryview]:
    """The header entries (tensor name -> dtype, shape, offsets) and the data section."""
    if len(blob) < _LENGTH.size:
        raise AdapterFormatError("adapter file is too short to be safetensors")
    (size,) = _LENGTH.unpack_from(blob)
    try:
        header = json.loads(blob[_LENGTH.size : _LENGTH.size + size])
    except ValueError as unreadable:
        raise AdapterFormatError(
            "adapter file has an unreadable safetensors header"
        ) from unreadable
    header.pop("__metadata__", None)
    return header, memoryview(blob)[_LENGTH.size + size :]


def peft_name(name: str) -> str:
    """PEFT's tensor name for an mlx-lm one. Raises AdapterFormatError on any other name."""
    module, _, side = name.rpartition(".")
    if side not in SIDES:
        raise AdapterFormatError(f"{name} is not an mlx-lm LoRA tensor (.lora_a or .lora_b)")
    return f"{PEFT_PREFIX}{module}.{SIDES[side]}.weight"


def _transposed(entry: Entry, data: memoryview) -> tuple[Entry, bytes]:
    """One tensor's PEFT header entry (without offsets) and its transposed bytes."""
    width = WIDTH.get(entry["dtype"])
    if width is None or len(entry["shape"]) != 2:
        raise AdapterFormatError(
            f"cannot convert a {entry['dtype']} tensor of shape {entry['shape']}"
        )
    start, end = entry["data_offsets"]
    raw = np.frombuffer(data[start:end], dtype=f"u{width}").reshape(entry["shape"])
    return {"dtype": entry["dtype"], "shape": entry["shape"][::-1]}, np.ascontiguousarray(
        raw.T
    ).tobytes()


def mlx_to_peft(blob: bytes) -> bytes:
    """The adapter file's bytes in the PEFT layout. Raises AdapterFormatError on anything else."""
    header, data = _read(blob)
    if not header:
        raise AdapterFormatError("adapter file holds no tensors")
    entries: dict[str, Entry] = {}
    body = bytearray()
    for name in sorted(header):
        meta, moved = _transposed(header[name], data)
        meta["data_offsets"] = [len(body), len(body) + len(moved)]
        entries[peft_name(name)] = meta
        body += moved
    head = json.dumps({"__metadata__": {"format": "pt"}, **entries}).encode()
    head += b" " * (-len(head) % 8)
    return _LENGTH.pack(len(head)) + head + bytes(body)
