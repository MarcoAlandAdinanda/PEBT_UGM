import itertools
import unittest

from gui import DemoRelayController
from relay_controller import (
    RelayCloseError,
    RelayCommandError,
    RelayConnectionError,
    RelayController,
    RelayLibraryError,
    RelayNotConnectedError,
    YDCI_OPEN_OUT_NOT_INIT,
    relay_states_for_sides,
)


class FakeFunction(object):
    def __init__(self, implementation):
        self.implementation = implementation
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.implementation(*args)


class FakeYdciLibrary(object):
    def __init__(self, open_code=0, output_code=0, status_code=0, close_code=1):
        self.open_code = open_code
        self.output_code = output_code
        self.status_code = status_code
        self.close_code = close_code
        self.open_arguments = None
        self.output_states = None
        self.status_states = (0, 0, 0, 0)
        self.closed_device = None
        self.YdciOpen = FakeFunction(self._open)
        self.YdciRlyOutput = FakeFunction(self._output)
        self.YdciRlyOutputStatus = FakeFunction(self._status)
        self.YdciClose = FakeFunction(self._close)

    def _open(self, board_id, device_name, device_pointer, reserved):
        self.open_arguments = (board_id, device_name, reserved)
        device_pointer._obj.value = 12
        return self.open_code

    def _output(self, device_id, output_data, offset, count):
        self.output_states = tuple(output_data[index] for index in range(count))
        self.status_states = self.output_states
        return self.output_code

    def _status(self, device_id, output_data, offset, count):
        for index in range(count):
            output_data[index] = self.status_states[index]
        return self.status_code

    def _close(self, device_id):
        self.closed_device = device_id.value
        return self.close_code


class SideMappingTests(unittest.TestCase):
    def test_every_side_combination_maps_to_expected_channels(self):
        for left, right, front in itertools.product((False, True), repeat=3):
            with self.subTest(left=left, right=right, front=front):
                self.assertEqual(
                    relay_states_for_sides(left, right, front),
                    (int(left), int(right), int(front), 0),
                )

    def test_fourth_relay_is_always_off(self):
        self.assertEqual(relay_states_for_sides(True, True, True)[3], 0)


class RelayControllerTests(unittest.TestCase):
    def test_connection_output_and_close_lifecycle(self):
        library = FakeYdciLibrary()
        controller = RelayController(loader=lambda name: library)

        self.assertEqual(controller.connect(), 12)
        self.assertTrue(controller.is_connected)
        self.assertEqual(
            library.open_arguments,
            (0, b"RLY-P4/2/0B-UBT", 0),
        )

        self.assertEqual(controller.set_states((1, 0, 1, 0)), 0)
        self.assertEqual(library.output_states, (1, 0, 1, 0))
        self.assertEqual(controller.get_states(), (1, 0, 1, 0))

        self.assertTrue(controller.close())
        self.assertEqual(library.closed_device, 12)
        self.assertFalse(controller.is_connected)

    def test_connect_is_idempotent(self):
        library = FakeYdciLibrary()
        controller = RelayController(loader=lambda name: library)
        self.assertEqual(controller.connect(), 12)
        self.assertEqual(controller.connect(), 12)

    def test_missing_library_is_reported(self):
        def missing_loader(name):
            raise OSError("not found")

        controller = RelayController(loader=missing_loader)
        with self.assertRaises(RelayLibraryError):
            controller.connect()

    def test_open_failure_is_reported(self):
        library = FakeYdciLibrary(open_code=7)
        controller = RelayController(loader=lambda name: library)
        with self.assertRaises(RelayConnectionError) as context:
            controller.connect()
        self.assertEqual(context.exception.code, 7)
        self.assertFalse(controller.is_connected)

    def test_output_failure_is_reported(self):
        library = FakeYdciLibrary(output_code=9)
        controller = RelayController(loader=lambda name: library)
        controller.connect()
        with self.assertRaises(RelayCommandError) as context:
            controller.set_states((0, 1, 0, 0))
        self.assertEqual(context.exception.code, 9)

    def test_close_failure_is_reported_and_connection_is_cleared(self):
        library = FakeYdciLibrary(close_code=0)
        controller = RelayController(loader=lambda name: library)
        controller.connect()
        with self.assertRaises(RelayCloseError) as context:
            controller.close()
        self.assertEqual(context.exception.code, 0)
        self.assertFalse(controller.is_connected)

    def test_invalid_state_count_is_rejected(self):
        controller = RelayController(loader=lambda name: FakeYdciLibrary())
        controller.connect()
        with self.assertRaises(ValueError):
            controller.set_states((1, 0, 1))

    def test_invalid_state_value_is_rejected(self):
        controller = RelayController(loader=lambda name: FakeYdciLibrary())
        controller.connect()
        with self.assertRaises(ValueError):
            controller.set_states((1, 0, 3, 0))

    def test_hold_state_is_forwarded_as_documented(self):
        library = FakeYdciLibrary()
        controller = RelayController(loader=lambda name: library)
        controller.connect()
        controller.set_states((1, 0, 2, 0))
        self.assertEqual(library.output_states, (1, 0, 2, 0))

    def test_open_mode_can_preserve_existing_outputs(self):
        library = FakeYdciLibrary()
        controller = RelayController(loader=lambda name: library)
        controller.connect(mode=YDCI_OPEN_OUT_NOT_INIT)
        self.assertEqual(library.open_arguments[-1], YDCI_OPEN_OUT_NOT_INIT)

    def test_status_failure_is_reported(self):
        library = FakeYdciLibrary(status_code=8)
        controller = RelayController(loader=lambda name: library)
        controller.connect()
        with self.assertRaises(RelayCommandError):
            controller.get_states()

    def test_operation_before_connect_is_rejected(self):
        controller = RelayController(loader=lambda name: FakeYdciLibrary())
        with self.assertRaises(RelayNotConnectedError):
            controller.set_states((0, 0, 0, 0))


class DemoControllerTests(unittest.TestCase):
    def test_demo_controller_records_the_applied_state(self):
        controller = DemoRelayController()
        self.assertEqual(controller.connect(), 0)
        controller.set_states((1, 1, 0, 0))
        self.assertEqual(controller.last_states, (1, 1, 0, 0))
        controller.close()
        self.assertFalse(controller.is_connected)


if __name__ == "__main__":
    unittest.main()
