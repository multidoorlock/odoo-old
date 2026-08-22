from .zkteco import ZKTecoAdapter


def get_adapter(device):
    if device.manufacturer == "zkteco":
        return ZKTecoAdapter(device)
    raise NotImplementedError(f"No adapter implemented for {device.manufacturer}")
