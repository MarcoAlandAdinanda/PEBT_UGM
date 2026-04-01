import sys
import ctypes
import time

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# IMPORTANT: The model name must match what the Ydci DLL expects internally.
# The Windows Device Manager shows "RLY-P4-U" but the DLL requires the full
# model designation "RLY-P4/2/0B-UBT".
DEVICE_NAME = b"RLY-P4/2/0B-UBT"
BOARD_ID    = 0                    # Board DIP-switch ID (usually 0)
NUM_RELAYS  = 4
RELAY_STATE = (1, 1, 1, 0)        # 1 = ON, 0 = OFF for each relay channel

# Relay 1 Rel Putih Kiri
# Relay 2 Rel Putih Kanan
# Relay 3 Rel Hitam

# ---------------------------------------------------------------------------
# Load Ydci DLL (cdecl calling convention — undecorated exports)
# ---------------------------------------------------------------------------
try:
    ydci = ctypes.cdll.LoadLibrary("Ydci")
    print("[OK]  Ydci DLL loaded successfully.")
except OSError as e:
    print(f"[FAIL] Could not load Ydci DLL: {e}")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Define ctypes argument / return types
#   YdciOpen(boardType: int, modelName: char*, id: short*, reserved: int) -> int
#   YdciRlyOutput(id: short, data: ubyte*, offset: int, count: int) -> int
#   YdciClose(id: short) -> int
# ---------------------------------------------------------------------------
ydci.YdciOpen.argtypes  = [ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_short), ctypes.c_int]
ydci.YdciOpen.restype   = ctypes.c_int

ydci.YdciRlyOutput.argtypes = [ctypes.c_short, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int, ctypes.c_int]
ydci.YdciRlyOutput.restype  = ctypes.c_int

ydci.YdciClose.argtypes = [ctypes.c_short]
ydci.YdciClose.restype  = ctypes.c_int

# ---------------------------------------------------------------------------
# Open the device
# ---------------------------------------------------------------------------
dev_id = ctypes.c_short()
result_open = ydci.YdciOpen(BOARD_ID, DEVICE_NAME, ctypes.byref(dev_id), 0)
print(f"Open  : code={result_open}, dev_id={dev_id.value}")

if result_open != 0:
    print(f"[FAIL] YdciOpen error {result_open} (hex: {result_open & 0xFFFFFFFF:#010x})")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Set relay outputs
# ---------------------------------------------------------------------------
try:
    output_data = (ctypes.c_ubyte * NUM_RELAYS)(*RELAY_STATE)
    result_output = ydci.YdciRlyOutput(dev_id, output_data, 0, NUM_RELAYS)
    print(f"Relay : code={result_output}, states={list(RELAY_STATE)}")

    if result_output != 0:
        print(f"[WARN] YdciRlyOutput error {result_output}")
    else:
        print("[OK]  Relay states applied successfully.")

except Exception as e:
    print(f"[FAIL] Exception: {e}")

# ---------------------------------------------------------------------------
# Close the device
# ---------------------------------------------------------------------------
finally:
    result_close = ydci.YdciClose(dev_id)
    print(f"Close : code={result_close}")

print("\nDone.")