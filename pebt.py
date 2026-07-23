"""Generate a paper-derived PEBT protocol for the generic experiment engine."""

from __future__ import absolute_import

import copy
import hashlib
import random


class PEBTGeneratorError(ValueError):
    """Raised when the compact PEBT generator configuration is invalid."""


def _mapping(value, path):
    if not isinstance(value, dict):
        raise PEBTGeneratorError("{0} must be an object.".format(path))
    return value


def _string(value, path):
    if not isinstance(value, str) or not value.strip():
        raise PEBTGeneratorError("{0} must be a non-empty string.".format(path))
    return value.strip()


def _integer(value, path, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise PEBTGeneratorError(
            "{0} must be an integer of at least {1}.".format(path, minimum)
        )
    return value


def _string_list(value, path):
    if not isinstance(value, list) or not value:
        raise PEBTGeneratorError("{0} must be a non-empty array.".format(path))
    result = []
    for index, item in enumerate(value):
        item = _string(item, "{0}[{1}]".format(path, index)).lower()
        if item in result:
            raise PEBTGeneratorError(
                "{0} contains duplicate value {1}.".format(path, item)
            )
        result.append(item)
    return result


def _frequency_values(value, path):
    value = _mapping(value, path)
    expanded = []
    for raw_value, raw_count in value.items():
        try:
            numeric_value = int(raw_value)
        except (TypeError, ValueError):
            raise PEBTGeneratorError(
                "{0} key {1!r} must be an integer.".format(path, raw_value)
            )
        if str(numeric_value) != str(raw_value):
            raise PEBTGeneratorError(
                "{0} key {1!r} must use canonical integer text.".format(
                    path, raw_value
                )
            )
        count = _integer(raw_count, "{0}.{1}".format(path, raw_value), minimum=1)
        expanded.extend([numeric_value] * count)
    return expanded


def _stable_seed(*parts):
    seed_text = "|".join(str(part) for part in parts)
    return int.from_bytes(
        hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big"
    )


def _choice_text(
    observer_label,
    light_count,
    dift_wait_seconds,
    sest_wait_seconds,
    difference_seconds,
    co2_liters_per_hour,
):
    return (
        "Pilih moda perjalanan untuk perjalanan berikutnya\n\n"
        "←  SEST                                      DIFT  →\n"
        "Waktu: {0} detik                         Waktu: {1} detik\n"
        "Lampu: 0 dari 12                         Lampu: {2} dari 12\n"
        "Emisi CO₂: 0 L/jam                       Emisi CO₂: {3} L/jam\n\n"
        "Selisih waktu SEST-DIFT: {4} detik\n"
        "Observer: {5}\n\n"
        "Tekan PANAH KIRI untuk SEST atau PANAH KANAN untuk DIFT."
    ).format(
        sest_wait_seconds,
        dift_wait_seconds,
        light_count,
        co2_liters_per_hour,
        difference_seconds,
        observer_label,
    )


def _pebt_trial(
    set_id,
    observer_label,
    light_block,
    set_trial_index,
    block_trial_index,
    dift_wait_seconds,
    difference_seconds,
    sest_key,
    dift_key,
):
    light_count = light_block["light_count"]
    relay_sides = light_block["relay_sides"]
    sest_wait_seconds = dift_wait_seconds + difference_seconds
    co2_liters_per_hour = light_count * 10
    trial_id = "{0}-{1}lights-{2:02d}".format(
        set_id.lower(), light_count, block_trial_index
    )
    condition = "{0}_{1}_lights".format(set_id.lower(), light_count)
    common_response_details = {
        "set_id": set_id,
        "set_trial_index": set_trial_index,
        "block_trial_index": block_trial_index,
        "light_count": light_count,
        "dift_wait_ms": dift_wait_seconds * 1000,
        "sest_wait_ms": sest_wait_seconds * 1000,
        "time_difference_ms": difference_seconds * 1000,
        "observer_label": observer_label,
    }
    sest_response_details = dict(common_response_details)
    sest_response_details.update(
        {
            "choice_label": "SEST",
            "pro_environmental": True,
            "selected_wait_ms": sest_wait_seconds * 1000,
            "selected_light_count": 0,
            "co2_liters_per_hour": 0,
        }
    )
    dift_response_details = dict(common_response_details)
    dift_response_details.update(
        {
            "choice_label": "DIFT",
            "pro_environmental": False,
            "selected_wait_ms": dift_wait_seconds * 1000,
            "selected_light_count": light_count,
            "co2_liters_per_hour": co2_liters_per_hour,
        }
    )
    response_details = {
        sest_key: sest_response_details,
        dift_key: dift_response_details,
    }
    return {
        "trial_id": trial_id,
        "condition": condition,
        "correct_key": None,
        "metadata": {
            "trial_role": "pebt_choice",
            "analysis_include": True,
            "set_id": set_id,
            "set_trial_index": set_trial_index,
            "block_trial_index": block_trial_index,
            "light_count": light_count,
            "relay_sides_for_dift": relay_sides,
            "dift_wait_seconds": dift_wait_seconds,
            "sest_wait_seconds": sest_wait_seconds,
            "time_difference_seconds": difference_seconds,
            "co2_liters_per_hour_dift": co2_liters_per_hour,
            "observer_label": observer_label,
            "response_details": response_details,
        },
        "phases": [
            {
                "name": "choice",
                "duration_ms": None,
                "text": _choice_text(
                    observer_label,
                    light_count,
                    dift_wait_seconds,
                    sest_wait_seconds,
                    difference_seconds,
                    co2_liters_per_hour,
                ),
                "lights": [],
                "collect_response": True,
                "allowed_keys": [sest_key, dift_key],
                "end_on_response": True,
                "font_size": 24,
            },
            {
                "name": "sest_wait",
                "duration_ms": sest_wait_seconds * 1000,
                "text": (
                    "menunggu...\n\nSEST dipilih\nLampu tidak menyala\n"
                    "Emisi CO₂: 0 L/jam"
                ),
                "lights": [],
                "collect_response": False,
                "run_if_response_key": sest_key,
                "font_size": 28,
            },
            {
                "name": "dift_wait",
                "duration_ms": dift_wait_seconds * 1000,
                "text": (
                    "menunggu...\n\nDIFT dipilih\n{0} lampu menyala\n"
                    "Emisi CO₂: {1} L/jam"
                ).format(light_count, co2_liters_per_hour),
                "lights": relay_sides,
                "collect_response": False,
                "run_if_response_key": dift_key,
                "font_size": 28,
            },
        ],
    }


def expand_pebt_configuration(data):
    """Expand a compact Yamawaki-style PEBT generator into generic blocks."""

    expanded = copy.deepcopy(data)
    generator = _mapping(expanded.get("generator"), "generator")
    generator_type = _string(generator.get("type"), "generator.type").lower()
    if generator_type != "pebt_yamawaki_2023":
        raise PEBTGeneratorError(
            "Unsupported generator.type {0}.".format(generator_type)
        )
    if expanded.get("blocks") not in (None, []):
        raise PEBTGeneratorError(
            "A generated PEBT configuration must not also define blocks."
        )

    random_seed = _integer(expanded.get("random_seed", 0), "random_seed")
    sest_key = _string(generator.get("sest_key", "left"), "generator.sest_key").lower()
    dift_key = _string(generator.get("dift_key", "right"), "generator.dift_key").lower()
    if sest_key == dift_key:
        raise PEBTGeneratorError("SEST and DIFT must use different keys.")

    dift_values = _frequency_values(
        generator.get("dift_wait_seconds"), "generator.dift_wait_seconds"
    )
    difference_values = _frequency_values(
        generator.get("time_difference_seconds"),
        "generator.time_difference_seconds",
    )
    if len(dift_values) != len(difference_values):
        raise PEBTGeneratorError(
            "DIFT wait and time-difference frequencies must have equal totals."
        )
    trials_per_set = len(dift_values)

    light_blocks_data = generator.get("light_blocks")
    if not isinstance(light_blocks_data, list) or not light_blocks_data:
        raise PEBTGeneratorError("generator.light_blocks must be a non-empty array.")
    light_blocks = []
    block_trial_total = 0
    for index, block_data in enumerate(light_blocks_data):
        path = "generator.light_blocks[{0}]".format(index)
        block_data = _mapping(block_data, path)
        light_count = _integer(block_data.get("light_count"), path + ".light_count", 1)
        relay_sides = _string_list(block_data.get("relay_sides"), path + ".relay_sides")
        trial_count = _integer(block_data.get("trial_count"), path + ".trial_count", 1)
        block_trial_total += trial_count
        light_blocks.append(
            {
                "light_count": light_count,
                "relay_sides": relay_sides,
                "trial_count": trial_count,
                "mapping_note": _string(
                    block_data.get("mapping_note"), path + ".mapping_note"
                ),
            }
        )
    if block_trial_total != trials_per_set:
        raise PEBTGeneratorError(
            "light_blocks trial_count total must equal {0}.".format(trials_per_set)
        )

    sets_data = generator.get("sets")
    if not isinstance(sets_data, list) or not sets_data:
        raise PEBTGeneratorError("generator.sets must be a non-empty array.")

    blocks = [
        {
            "block_id": "lamp-confirmation",
            "instructions": (
                "Konfirmasi hardware berdasarkan Appendix D: setelah siap, tekan "
                "SPASI. Semua 12 lampu akan menyala selama 10 detik."
            ),
            "repetitions": 1,
            "randomize_trials": False,
            "trials": [
                {
                    "trial_id": "lamp-confirmation-12-lights",
                    "condition": "hardware_confirmation",
                    "correct_key": None,
                    "metadata": {
                        "trial_role": "lamp_confirmation",
                        "analysis_include": False,
                        "paper_duration_seconds": 10,
                        "light_count": 12,
                    },
                    "phases": [
                        {
                            "name": "lamp_confirmation",
                            "duration_ms": 10000,
                            "text": (
                                "KONFIRMASI LAMPU\n\n12 lampu menyala selama 10 detik."
                            ),
                            "lights": ["left", "right", "front"],
                            "collect_response": False,
                            "font_size": 30,
                        }
                    ],
                }
            ],
        }
    ]

    known_set_ids = set()
    for set_index, set_data in enumerate(sets_data):
        path = "generator.sets[{0}]".format(set_index)
        set_data = _mapping(set_data, path)
        set_id = _string(set_data.get("set_id"), path + ".set_id").upper()
        if set_id in known_set_ids:
            raise PEBTGeneratorError("Duplicate PEBT set_id: {0}.".format(set_id))
        known_set_ids.add(set_id)
        observer_label = _string(
            set_data.get("observer_label"), path + ".observer_label"
        )
        contact_instruction = set_data.get("contact_instruction", "")
        if contact_instruction:
            contact_instruction = _string(
                contact_instruction, path + ".contact_instruction"
            )

        shuffled_dift = list(dift_values)
        shuffled_differences = list(difference_values)
        factor_rng = random.Random(
            _stable_seed(random_seed, set_id, "pebt-factor-pairing")
        )
        factor_rng.shuffle(shuffled_dift)
        factor_rng.shuffle(shuffled_differences)
        factor_pairs = list(zip(shuffled_dift, shuffled_differences))

        pair_offset = 0
        set_trial_index = 0
        for block_index, light_block in enumerate(light_blocks):
            block_trial_count = light_block["trial_count"]
            block_pairs = factor_pairs[pair_offset : pair_offset + block_trial_count]
            pair_offset += block_trial_count
            trials = []
            for block_trial_index, pair in enumerate(block_pairs, start=1):
                set_trial_index += 1
                trials.append(
                    _pebt_trial(
                        set_id=set_id,
                        observer_label=observer_label,
                        light_block=light_block,
                        set_trial_index=set_trial_index,
                        block_trial_index=block_trial_index,
                        dift_wait_seconds=pair[0],
                        difference_seconds=pair[1],
                        sest_key=sest_key,
                        dift_key=dift_key,
                    )
                )

            instructions = (
                "{0} - blok {1} lampu ({2} trial). DIFT menyalakan {1} lampu; "
                "SEST tidak menyalakan lampu. {3}"
            ).format(
                set_id,
                light_block["light_count"],
                block_trial_count,
                light_block["mapping_note"],
            )
            if block_index == 0 and contact_instruction:
                instructions = contact_instruction + "\n\n" + instructions

            blocks.append(
                {
                    "block_id": "{0}-{1}-lights".format(
                        set_id.lower(), light_block["light_count"]
                    ),
                    "instructions": instructions,
                    "repetitions": 1,
                    "randomize_trials": True,
                    "trials": trials,
                }
            )

    expanded["blocks"] = blocks
    return expanded
