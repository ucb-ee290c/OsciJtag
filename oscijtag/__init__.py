"""
# OsciBear JTAG Access

Via `pyftdi`, the FTDI USB-JTAG chip, and the Olimex ARM-USB-TINY-H adapter which uses it. 

Adapted from PyFTDI's JTAG unit-test: 
https://github.com/eblot/pyftdi/blob/master/pyftdi/tests/jtag.py
"""

__version__ = "0.1.0"

from dataclasses import dataclass, asdict
from pyftdi.jtag import JtagEngine, JtagTool
from pyftdi.bits import BitSequence


@dataclass
class FtdiUsbJtagDeviceInfo:
    """ # FtdiUsbJtagDeviceInfo 

    Info required to connect to an FTDI-based USB-JTAG adapter, 
    bypassing `pyftdi`'s URL scheme, largely as it expects the FTDI (company)'s ID-codes. 
    
    Note these field-names correspond to the arguments to `ftdi.open_mpsse`, 
    used below to create a connection. """

    vendor: int  # Vendor ID
    product: int  # Product ID
    interface: int  # Interface number (usually 1)


# Create the Olimex Jtag adapter's info.
#
# From https://www.olimex.com/Products/ARM/JTAG/ARM-USB-TINY-H/ -
# Q: I am currently using operating system X. It has FTDI drivers, how should I alter them to work with my installation?
# A: FTDI provide drivers and instructions at their web site, download them and use our ARM-USB-TINY-H PID: 0x002a, VID: 0x15BA to install the drivers.
#
OlimexArmJtag = FtdiUsbJtagDeviceInfo(product=0x002A, vendor=0x15BA, interface=1)

# Create the Jtag Engine
# The `trst=True` option has been observed to be important, although it's not clear why it should be.
jtag = JtagEngine(trst=True, frequency=1e5)

# Configuring the adapter requires reaching a few levels into `jtag`, rather than using `pyftdi`'s default URL scheme.
jtag.controller.ftdi.open_mpsse(**asdict(OlimexArmJtag))

# Also create their `JtagTool`, a self-described "helper class with facility functions".
tool = JtagTool(jtag)

# Auto-detect the instruction register length

jtag.reset()
jtag.go_idle()
jtag.capture_ir()
irlen = tool.detect_register_size()
print(f"Detected IR Length={irlen}")


# # RISC-V Jtag Registers
# Taps spelled out by the RISC-V Debug Spec
RiscvJtagRegs = {
    # BYPASS is also at reserved addresses 0x12 through 0x1F
    "BYPASS": BitSequence("00000", msb=True, length=5),
    "IDCODE": BitSequence("00001", msb=True, length=5),
    "DTMCS": BitSequence("10000", msb=True, length=5),
    "DMI": BitSequence("10001", msb=True, length=5),
}

# Read the default data-register, IDCODE
jtag.reset()
idcode = jtag.read_dr(32)
idcode = int(idcode)

if idcode == 0x20000913:
    print(f"Detected the SiFive IDCODE 0x20000913")
elif idcode == 0x1:
    print(f"Detected the default IDCODE 0x00000001 (probably a student chip)")
else:
    raise ValueError(f"Unknown IDCODE: 0x{idcode:x}")


# Test the BYPASS instruction using shift_and_update_register
jtag.reset()
instruction = RiscvJtagRegs["BYPASS"]
jtag.change_state("shift_ir")
retval = jtag.shift_and_update_register(instruction)
print("retval: 0x%x" % int(retval))
jtag.go_idle()
jtag.change_state("shift_dr")
_in = BitSequence("011011110000" * 2, length=24)
out = jtag.shift_and_update_register(_in)
jtag.go_idle()
print("BYPASS sent: %s, received: %s  (should be left shifted by one)" % (_in, out))

