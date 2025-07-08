class Command:
    def __init__(self, command: int):
        self.command = command


class Command_0(Command):
    """
    Drive Forward M1

    Drive motor 1 forward. Valid data range is 0 - 127. A value of 127 = full speed forward, 64 = about half speed forward and 0 = full stop.
    Send: [Address, 0, Value, CRC(2 bytes)]
    Receive: [0xFF]
    """

    def __init__(self):
        super().__init__(0)

    def recv(self):
        return [0xFF]  # Simulated response for the command
