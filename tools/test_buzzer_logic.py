"""Quick interactive buzzer logic diagnostic for Raspberry Pi."""

import time
import sys

try:
    from gpiozero import OutputDevice
    from gpiozero import Device
    try:
        from gpiozero.pins.lgpio import LGPIOFactory
        Device.pin_factory = LGPIOFactory()
    except Exception:
        pass
except ImportError:
    print("gpiozero not installed.")
    sys.exit(1)

pin = 17
print("=" * 60)
print("  BUZZER POLARITY DIAGNOSTIC TEST")
print("=" * 60)

dev = OutputDevice(pin, active_high=True, initial_value=False)

print("\n[Step 1] Setting GPIO 17 to LOW (0V) for 3 seconds...")
print("  --> Listen: Is it buzzing now? (YES = Active-Low module)")
dev.off()
time.sleep(3.0)

print("\n[Step 2] Setting GPIO 17 to HIGH (3.3V) for 3 seconds...")
print("  --> Listen: Is it buzzing now? (YES = Active-High module)")
dev.on()
time.sleep(3.0)

print("\n[Step 3] Shutting buzzer OFF...")
dev.off()
dev.close()

print("\nResult summary:")
print("  * If it buzzed during [Step 1] (0V), run with: --buzzer-active-low")
print("  * If it buzzed during [Step 2] (3.3V), run normally without any extra flags.")
print("=" * 60)
