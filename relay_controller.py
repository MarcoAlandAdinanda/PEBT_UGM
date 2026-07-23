"""Reusable hardware controller for the RLY-P4-U USB relay board."""

from __future__ import absolute_import

import ctypes
import platform


DEVICE_NAME = b"RLY-P4/2/0B-UBT"
BOARD_ID = 0
NUM_RELAYS = 4
DEFAULT_RELAY_STATE = (1, 1, 1, 0)
YDCI_RESULT_SUCCESS = 0
YDCI_OPEN_NORMAL = 0
YDCI_OPEN_OUT_NOT_INIT = 1
YDCI_OUTPUT_OFF = 0
YDCI_OUTPUT_ON = 1
YDCI_OUTPUT_HOLD = 2

YDCI_ERROR_DETAILS = {
    -838860799: "General error; check whether the USB cable was disconnected.",
    -838860798: "The board is not open.",
    -838860797: "The board is already open.",
    -838860796: "The device ID is invalid.",
    -838860794: "The board cannot be opened; check USB connection and board ID.",
    -838860792: "One or more API parameters are invalid.",
    -838860791: "The driver could not allocate memory.",
    -838860790: "The model name is invalid or unsupported.",
    -838860788: "The requested function is not supported.",
    -838860781: "The board selector is invalid; use a value from 0 to 15.",
    -822083585: "Fatal Ydci driver error; contact vendor support.",
}

# Physical setup mapping derived from the original script:
# Relay 1 = left lamp row, Relay 2 = right lamp row,
# Relay 3 = front lamp row (the black rail), Relay 4 = unused.
SIDE_TO_RELAY = {
    "left": 0,
    "right": 1,
    "front": 2,
}


class RelayError(RuntimeError):
    """Base error for relay setup and communication failures."""


class RelayLibraryError(RelayError):
    """Raised when the vendor DLL cannot be loaded."""


class RelayConnectionError(RelayError):
    """Raised when the relay board cannot be opened."""

    def __init__(self, code):
        self.code = code
        detail = YDCI_ERROR_DETAILS.get(code, "Unknown Ydci error.")
        super(RelayConnectionError, self).__init__(
            "YdciOpen failed with code {0} ({1:#010x}). {2}".format(
                code, code & 0xFFFFFFFF, detail
            )
        )


class RelayCommandError(RelayError):
    """Raised when a relay output command fails."""

    def __init__(self, code):
        self.code = code
        detail = YDCI_ERROR_DETAILS.get(code, "Unknown Ydci error.")
        super(RelayCommandError, self).__init__(
            "Ydci relay command failed with code {0} ({1:#010x}). {2}".format(
                code, code & 0xFFFFFFFF, detail
            )
        )


class RelayCloseError(RelayError):
    """Raised when closing the relay board fails."""

    def __init__(self, code):
        self.code = code
        super(RelayCloseError, self).__init__("YdciClose returned FALSE.")


class RelayNotConnectedError(RelayError):
    """Raised when an operation requires an open board."""


class DemoRelayController(object):
    """In-memory controller for the local Web UI simulation mode."""

    def __init__(self):
        self._is_connected = False
        self._device_id = None
        self.last_states = (0, 0, 0, 0)

    @property
    def is_connected(self):
        return self._is_connected

    @property
    def device_id(self):
        return self._device_id

    def connect(self, mode=YDCI_OPEN_NORMAL):
        self._is_connected = True
        self._device_id = 0
        return self._device_id

    def set_states(self, states):
        if not self.is_connected:
            raise RelayNotConnectedError("Open the demo relay before setting outputs.")
        normalized = tuple(int(value) for value in states)
        if len(normalized) != NUM_RELAYS:
            raise ValueError("Exactly four relay states are required.")
        if any(value not in (0, 1, 2) for value in normalized):
            raise ValueError("Demo relay states must be 0, 1, or 2.")
        self.last_states = normalized
        return YDCI_RESULT_SUCCESS

    def get_states(self):
        if not self.is_connected:
            raise RelayNotConnectedError("Open the demo relay before reading outputs.")
        return self.last_states

    def close(self):
        self._is_connected = False
        self._device_id = None
        return True


def _default_library_loader(dll_name):
    """Load the vendor library using the platform convention in Y2's sample."""

    system_name = platform.system()
    if system_name == "Windows":
        return ctypes.windll.LoadLibrary(dll_name)
    if system_name == "Linux":
        library_name = "libydci.so" if dll_name == "Ydci" else dll_name
        return ctypes.CDLL(library_name)
    raise OSError("Ydci supports Windows and Linux; found {0}.".format(system_name))


def relay_states_for_sides(left=False, right=False, front=False):
    """Return the four-channel relay tuple for the three physical lamp rows."""

    states = [0] * NUM_RELAYS
    states[SIDE_TO_RELAY["left"]] = int(bool(left))
    states[SIDE_TO_RELAY["right"]] = int(bool(right))
    states[SIDE_TO_RELAY["front"]] = int(bool(front))
    return tuple(states)


class RelayController(object):
    """Manage one connection to the Ydci relay DLL."""

    def __init__(
        self,
        dll_name="Ydci",
        device_name=DEVICE_NAME,
        board_id=BOARD_ID,
        loader=None,
    ):
        self.dll_name = dll_name
        self.device_name = device_name
        self.board_id = board_id
        self._loader = loader or _default_library_loader
        self._library = None
        self._device_id = None

    @property
    def is_connected(self):
        return self._device_id is not None

    @property
    def device_id(self):
        return None if self._device_id is None else self._device_id.value

    def _load_library(self):
        if self._library is not None:
            return

        try:
            self._library = self._loader(self.dll_name)
        except OSError as exc:
            raise RelayLibraryError(
                "Could not load {0}: {1}".format(self.dll_name, exc)
            )

        self._library.YdciOpen.argtypes = [
            ctypes.c_ushort,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_ushort),
            ctypes.c_ushort,
        ]
        self._library.YdciOpen.restype = ctypes.c_int

        self._library.YdciRlyOutput.argtypes = [
            ctypes.c_ushort,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_ushort,
            ctypes.c_ushort,
        ]
        self._library.YdciRlyOutput.restype = ctypes.c_int

        if hasattr(self._library, "YdciRlyOutputStatus"):
            self._library.YdciRlyOutputStatus.argtypes = [
                ctypes.c_ushort,
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_ushort,
                ctypes.c_ushort,
            ]
            self._library.YdciRlyOutputStatus.restype = ctypes.c_int

        self._library.YdciClose.argtypes = [ctypes.c_ushort]
        self._library.YdciClose.restype = ctypes.c_int

    def connect(self, mode=YDCI_OPEN_NORMAL):
        """Load the DLL and open the board; normal mode switches outputs OFF."""

        if self.is_connected:
            return self.device_id
        if not 0 <= self.board_id <= 15:
            raise ValueError("Board ID must be between 0 and 15.")
        if mode not in (YDCI_OPEN_NORMAL, YDCI_OPEN_OUT_NOT_INIT):
            raise ValueError("Open mode must be 0 (normal) or 1 (keep outputs).")

        self._load_library()
        device_id = ctypes.c_ushort()
        result = self._library.YdciOpen(
            self.board_id,
            self.device_name,
            ctypes.byref(device_id),
            mode,
        )
        if result != YDCI_RESULT_SUCCESS:
            raise RelayConnectionError(result)

        self._device_id = device_id
        return self.device_id

    def set_states(self, states):
        """Apply four ON/OFF values to relay channels 1 through 4."""

        normalized = tuple(states)
        if len(normalized) != NUM_RELAYS:
            raise ValueError("Exactly four relay states are required.")
        if any(state not in (0, 1, 2, False, True) for state in normalized):
            raise ValueError("Relay states must contain only 0 (OFF), 1 (ON), or 2 (hold).")
        if not self.is_connected:
            raise RelayNotConnectedError("Open the relay board before setting outputs.")

        normalized = tuple(int(state) for state in normalized)
        output_data = (ctypes.c_ubyte * NUM_RELAYS)(*normalized)
        result = self._library.YdciRlyOutput(
            self._device_id,
            output_data,
            0,
            NUM_RELAYS,
        )
        if result != YDCI_RESULT_SUCCESS:
            raise RelayCommandError(result)
        return result

    def get_states(self):
        """Read and return the current state of all four relay outputs."""

        if not self.is_connected:
            raise RelayNotConnectedError("Open the relay board before reading outputs.")
        if not hasattr(self._library, "YdciRlyOutputStatus"):
            raise RelayLibraryError("YdciRlyOutputStatus is unavailable in this driver.")

        output_status = (ctypes.c_ubyte * NUM_RELAYS)()
        result = self._library.YdciRlyOutputStatus(
            self._device_id,
            output_status,
            0,
            NUM_RELAYS,
        )
        if result != YDCI_RESULT_SUCCESS:
            raise RelayCommandError(result)
        return tuple(output_status)

    def close(self):
        """Close the active relay connection."""

        if not self.is_connected:
            return True

        device_id = self._device_id
        self._device_id = None
        result = self._library.YdciClose(device_id)
        if not result:
            raise RelayCloseError(result)
        return True

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
