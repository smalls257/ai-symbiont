"""The mlx-to-PEFT conversion keeps every value and renames and transposes as PEFT expects.

Violation prevented: Distributed Monolith. The trainer and the judge server share only this file
layout, so a wrong rename here is a judge that loads and answers with an untrained adapter.
"""

import json
import struct

import numpy as np
import pytest

from symbiont.service.nightly_peft import AdapterFormatError, mlx_to_peft, peft_name


def safetensors(tensors, dtype="F32", np_dtype="<f4"):
    header, body = {}, b""
    for name, array in tensors.items():
        raw = np.ascontiguousarray(array.astype(np_dtype)).tobytes()
        header[name] = {
            "dtype": dtype,
            "shape": list(array.shape),
            "data_offsets": [len(body), len(body) + len(raw)],
        }
        body += raw
    head = json.dumps({"__metadata__": {"format": "mlx"}, **header}).encode()
    return struct.pack("<Q", len(head)) + head + body


def parsed(blob):
    (size,) = struct.unpack_from("<Q", blob)
    header = json.loads(blob[8 : 8 + size])
    data = blob[8 + size :]
    out = {}
    for name, entry in header.items():
        if name == "__metadata__":
            continue
        start, end = entry["data_offsets"]
        out[name] = np.frombuffer(data[start:end], dtype="<f4").reshape(entry["shape"])
    return out


def test_names_and_shapes_follow_peft_and_values_are_transposed_not_changed():
    a = np.arange(12, dtype="<f4").reshape(6, 2)  # mlx lora_a: (in, r)
    b = np.arange(10, dtype="<f4").reshape(2, 5)  # mlx lora_b: (r, out)
    blob = safetensors(
        {"model.layers.0.self_attn.q_proj.lora_a": a, "model.layers.0.self_attn.q_proj.lora_b": b}
    )
    converted = parsed(mlx_to_peft(blob))
    prefix = "base_model.model.model.layers.0.self_attn.q_proj"
    assert converted[f"{prefix}.lora_A.weight"].shape == (2, 6)
    assert converted[f"{prefix}.lora_B.weight"].shape == (5, 2)
    np.testing.assert_array_equal(converted[f"{prefix}.lora_A.weight"], a.T)
    np.testing.assert_array_equal(converted[f"{prefix}.lora_B.weight"], b.T)


def test_bfloat16_bytes_survive_unchanged():
    raw = np.arange(6, dtype="<u2").reshape(3, 2)
    blob = safetensors({"m.lora_a": raw}, dtype="BF16", np_dtype="<u2")
    (size,) = struct.unpack_from("<Q", mlx_to_peft(blob))
    out = mlx_to_peft(blob)
    header = json.loads(out[8 : 8 + size])
    assert header["base_model.model.m.lora_A.weight"]["dtype"] == "BF16"
    body = np.frombuffer(out[8 + size :], dtype="<u2").reshape(2, 3)
    np.testing.assert_array_equal(body, raw.T)


def test_a_tensor_that_is_not_lora_raises_naming_it():
    with pytest.raises(AdapterFormatError, match="model.norm.weight"):
        mlx_to_peft(safetensors({"model.norm.weight": np.zeros((2, 2))}))


def test_garbage_and_empty_files_raise_instead_of_producing_an_empty_adapter():
    with pytest.raises(AdapterFormatError):
        mlx_to_peft(b"nope")
    with pytest.raises(AdapterFormatError, match="no tensors"):
        mlx_to_peft(safetensors({}))


def test_peft_name_maps_both_sides():
    assert peft_name("x.y.lora_a") == "base_model.model.x.y.lora_A.weight"
    assert peft_name("x.y.lora_b") == "base_model.model.x.y.lora_B.weight"
