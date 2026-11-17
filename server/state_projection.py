"""Versioned state selection shared by decoder and private worker boundaries."""
_UNSET = object()
PROJECTION_VERSION = 1
STATE_MODES = ("summary", "full", "ownership")


def resolve_mode(include_entities=_UNSET, mode=None):
    """Return selected shape; preserve omitted versus explicit legacy boolean."""
    if mode is not None:
        if type(mode) is not str or mode not in STATE_MODES:
            raise ValueError("invalid state mode")
        if include_entities is not _UNSET:
            raise ValueError("mode and include_entities cannot be combined")
        return mode
    if include_entities is not _UNSET and type(include_entities) is not bool:
        raise ValueError("include_entities must be boolean")
    return "full" if include_entities is True else "summary"


def projection_request(value):
    if (type(value) is not dict or value.keys() != {"version", "step_mode"}
            or type(value["version"]) is not int or value["version"] != PROJECTION_VERSION):
        raise ValueError("invalid state projection version/schema")
    resolve_mode(mode=value["step_mode"])
    if value["step_mode"] is None:
        raise ValueError("invalid state projection mode")
    return value["step_mode"]


def validate_state(state, viewer, mode, *, synthetic=False, game_data_sha256=None, wire=False):
    """Validate complete selected output; coordinator cannot rehash absent raw bytes."""
    from .rust_snapshot_decoder import validate_state_shape, _integer, _require, _HEX64
    if not synthetic:
        if not wire and type(state) is dict and type(state.get("resources")) is dict:
            resources = {str(k) if type(k) is int else k: v for k, v in state["resources"].items()}
            _require(len(resources) == len(state["resources"]), "resource ID aliases")
            state = {**state, "resources": resources}
        return validate_state_shape(state, None, viewer, mode=mode)
    keys = {"frame", "viewer", "synthetic_test_backend", "game_data_sha256", "resources", "game_state"}
    if mode != "summary":
        keys.add("entities" if mode == "full" else "ownership")
    _require(type(state) is dict and state.keys() == keys, "synthetic state keys")
    _require(_integer(state["frame"], -1, 0x7fffffff) and _integer(state["viewer"], 0, 31)
             and state["viewer"] == viewer and state["synthetic_test_backend"] is True,
             "synthetic state values")
    digest = state["game_data_sha256"]
    _require(type(digest) is str and _HEX64.fullmatch(digest)
             and (game_data_sha256 is None or digest == game_data_sha256), "synthetic game data digest")
    resources = state["resources"]
    key = "0" if wire else 0
    _require(type(resources) is dict and resources.keys() == {key}
             and all(type(k) is (str if wire else int) for k in resources)
             and type(resources[key]) is dict and resources[key].keys() == {"primary"}
             and _integer(resources[key]["primary"], 0, 0x80000000), "synthetic resources")
    game = state["game_state"]
    _require(type(game) is dict and game.keys() == {"complete", "game_over_frame", "winning_alliance",
             "army_conceded_flag", "game_over_checksum"}, "synthetic game state keys")
    _require(type(game["complete"]) is bool and _integer(game["game_over_frame"], -1, 0x7fffffff)
             and _integer(game["winning_alliance"]) and _integer(game["army_conceded_flag"])
             and _integer(game["game_over_checksum"], 0, (1 << 64)-1), "synthetic game state values")
    if mode != "summary":
        records = state["entities" if mode == "full" else "ownership"]
        _require(type(records) is list and len(records) == 1 and type(records[0]) is dict
                 and records[0].keys() == {"id", "army", "type"}
                 and all(_integer(v) for v in records[0].values())
                 and records[0] == {"id": 0, "army": 0, "type": 1}, "synthetic records")
    state["resources"] = {0: resources[key]}
    return state
