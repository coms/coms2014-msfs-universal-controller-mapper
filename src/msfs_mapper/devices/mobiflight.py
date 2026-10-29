"""Device definition for the companion MobiFlight Mega serial firmware."""

from __future__ import annotations

from msfs_mapper.models import ControlKind, DeviceDefinition, PhysicalControl


def mega_definition(buttons: int = 8, encoders: int = 2) -> DeviceDefinition:
    if not 0 <= buttons <= 32 or not 0 <= encoders <= 3:
        raise ValueError("MobiFlight Mega supports 0-32 buttons and 0-3 encoders")

    controls = [
        PhysicalControl(
            id=f"button_{index + 1}",
            kind=ControlKind.BUTTON,
            label=f"Button {index + 1}",
            button=index,
        )
        for index in range(buttons)
    ]
    controls.extend(
        PhysicalControl(
            id=f"encoder_{index + 1}",
            kind=ControlKind.ENCODER,
            label=f"Encoder {index + 1}",
            roles=["encoder"],
            inc_button=buttons + index * 2,
            dec_button=buttons + index * 2 + 1,
        )
        for index in range(encoders)
    )
    return DeviceDefinition(
        name="MobiFlight Mega (custom serial firmware)",
        manufacturer="MobiFlight",
        vendor_id=0xFFFF,
        product_id=0x0001,
        controls=controls,
    )
