class AttendanceDeviceAdapter:
    def __init__(self, device):
        self.device = device
        self.env = device.env

    def build_command(self, command_type, device_employee):
        raise NotImplementedError

    def process_payload(self, log, request_type, raw_body, body_text):
        raise NotImplementedError

    def map_punch_state(self, raw_value):
        raise NotImplementedError
