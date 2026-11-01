"""bleak.exc: the errors the Studio's client catches."""


class BleakError(Exception):
    pass


class BleakCharacteristicNotFoundError(BleakError):
    pass
