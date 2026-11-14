"""World manifest: defaults, validation, hashing and perception offsets (M1)."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cellgame.shared.manifest import (
    ManifestError,
    build_manifest,
    default_manifest,
    is_legacy,
    manifest_hash,
    perception_offsets,
)


def expect_error(overrides, fragment):
    try:
        build_manifest(overrides)
    except ManifestError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"expected ManifestError for {overrides!r}")


def test_default_is_legacy():
    manifest = default_manifest()
    assert manifest["manifest_version"] == 1
    assert is_legacy(manifest)
    assert manifest["perception"]["model"] == "legacy"
    assert manifest["observation"] == {"version": 1, "coordinates": "absolute"}
    assert (manifest["world"]["width"], manifest["world"]["height"]) == (256, 256)
    names = [action["name"] for action in manifest["actions"]]
    assert names[:3] == ["move", "attack", "reproduce"] and "move_group" in names


def test_radius_override_switches_to_observation_v2():
    manifest = build_manifest({"perception": {"model": "radius", "radius": 2}})
    assert not is_legacy(manifest)
    assert manifest["perception"] == {"model": "radius", "radius": 2, "metric": "chebyshev"}
    assert manifest["observation"]["version"] == 2


def test_world_size_override():
    manifest = build_manifest({"world": {"width": 64, "height": 48}})
    assert (manifest["world"]["width"], manifest["world"]["height"]) == (64, 48)


def test_invalid_overrides_are_rejected():
    expect_error({"weather": {}}, "weather")
    expect_error({"perception": {"model": "telepathy"}}, "model")
    expect_error({"perception": {"model": "radius", "radius": 0}}, "radius")
    expect_error({"perception": {"model": "radius", "radius": 9}}, "radius")
    expect_error({"perception": {"model": "radius", "radius": True}}, "radius")
    expect_error({"perception": {"model": "radius", "metric": "manhattan"}}, "metric")
    expect_error({"perception": {"model": "radius", "radius": 1, "metric": "euclidean"}}, "euclidean")
    expect_error({"perception": {"model": "radius", "fov": 3}}, "fov")
    expect_error({"observation": {"coordinates": "relative"}}, "relative")
    expect_error({"observation": {"version": 2}}, "version")
    expect_error({"world": {"width": 8}}, "width")
    expect_error({"world": {"width": 1024}}, "width")
    expect_error({"world": {"topology": "torus"}}, "torus")
    expect_error({"actions": []}, "actions")
    expect_error({"manifest_version": 2}, "manifest_version")
    expect_error([], "对象")


def test_build_does_not_mutate_input():
    overrides = {"perception": {"model": "radius", "radius": 3}}
    before = copy.deepcopy(overrides)
    manifest = build_manifest(overrides)
    manifest["perception"]["radius"] = 1
    assert overrides == before
    assert build_manifest(overrides)["perception"]["radius"] == 3


def test_hash_is_stable_and_content_sensitive():
    a = build_manifest({"perception": {"model": "radius", "radius": 2}})
    b = build_manifest({"perception": {"radius": 2, "model": "radius"}})
    c = build_manifest({"perception": {"model": "radius", "radius": 3}})
    assert manifest_hash(a) == manifest_hash(b)
    assert manifest_hash(a) != manifest_hash(c)
    assert manifest_hash(a).startswith("sha256:")


def test_perception_offsets():
    legacy = perception_offsets(default_manifest())
    assert legacy == [(dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
    square = perception_offsets(build_manifest({"perception": {"model": "radius", "radius": 2}}))
    assert len(square) == 25 and square[0] == (-2, -2) and square[-1] == (2, 2)
    disc = perception_offsets(build_manifest(
        {"perception": {"model": "radius", "radius": 2, "metric": "euclidean"}}))
    assert len(disc) == 13 and (2, 0) in disc and (2, 1) not in disc and (1, 1) in disc


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("MANIFEST TEST PASSED")


if __name__ == "__main__":
    main()
