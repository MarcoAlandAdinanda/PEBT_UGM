"""Command-line entry point for the RLY-P4-U relay controller."""

from relay_controller import (
    BOARD_ID,
    DEFAULT_RELAY_STATE,
    DEVICE_NAME,
    RelayCommandError,
    RelayController,
    RelayError,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# IMPORTANT: The model name must match what the Ydci DLL expects internally.
# The Windows Device Manager shows "RLY-P4-U" but the DLL requires the full
# model designation "RLY-P4/2/0B-UBT".
RELAY_STATE = DEFAULT_RELAY_STATE  # 1 = ON, 0 = OFF for each relay channel

# Relay 1 Rel Putih Kiri
# Relay 2 Rel Putih Kanan
# Relay 3 Deret Depan (rel hitam pada setup awal)


def main():
    """Apply the original default state and return a process exit code."""

    controller = RelayController(
        device_name=DEVICE_NAME,
        board_id=BOARD_ID,
    )
    exit_code = 0

    try:
        dev_id = controller.connect()
        print("[OK]  Ydci DLL loaded successfully.")
        print("Open  : code=0, dev_id={0}".format(dev_id))

        try:
            controller.set_states(RELAY_STATE)
            print("Relay : code=0, states={0}".format(list(RELAY_STATE)))
            print("[OK]  Relay states applied successfully.")
        except RelayCommandError as exc:
            print("Relay : code={0}, states={1}".format(exc.code, list(RELAY_STATE)))
            print("[WARN] {0}".format(exc))
            exit_code = 1

    except RelayError as exc:
        print("[FAIL] {0}".format(exc))
        exit_code = 1

    finally:
        if controller.is_connected:
            try:
                result_close = controller.close()
                print("Close : success={0}".format(result_close))
            except RelayError as exc:
                print("[WARN] {0}".format(exc))
                exit_code = 1

    print("\nDone.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
