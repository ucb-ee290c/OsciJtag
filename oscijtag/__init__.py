"""
# OsciBear JTAG Access

Via `pyftdi`, the FTDI USB-JTAG chip, and the Olimex ARM-USB-TINY-H adapter which uses it. 

Adapted from PyFTDI's JTAG unit-test: 
https://github.com/eblot/pyftdi/blob/master/pyftdi/tests/jtag.py
"""

__version__ = "0.1.0"

from dataclasses import dataclass, asdict
from typing import Optional

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


"""
# RISC-V Jtag Registers
Taps spelled out by the RISC-V Debug Spec 
"""
RiscvJtagRegs = {
    # BYPASS is also available at reserved addresses 0x12 through 0x1F
    "BYPASS": BitSequence("00000", msb=True, length=5),
    "IDCODE": BitSequence("00001", msb=True, length=5),
    "DTMCS": BitSequence("10000", msb=True, length=5),
    "DMI": BitSequence("10001", msb=True, length=5),
}


""" 
Enumerated, Known JTAG IDCODE Values. 
Keys are integer code-values, and values are a string description of the device.
"""
JtagIdCodes = {
    0x00000001: "DEFAULT",  # Default ID
    0x20000913: "SIFIVE",  # SiFive FE310, as in the SparkFun RedBoard
}


def detect_irlen() -> int:
    """ Auto-detect the instruction register length"""

    # Create the `JtagTool`, a self-described "helper class with facility functions".
    tool = JtagTool(jtag)

    jtag.reset()
    jtag.go_idle()
    jtag.capture_ir()
    irlen = tool.detect_register_size()

    # All of the RISC-V stuff we're testing has IRLEN=5. Check that, and generalize this if we ever wanna use other devices.
    if irlen != 5:
        raise ValueError(f"IR length is {irlen}, expected 5")
    print(f"Detected IR Length={irlen}")

    jtag.reset()
    return irlen


def read_idcode() -> int:
    """ Read the default data-register, IDCODE. 
    Check for existence in our know-good values dict. 
    Returns the integer id-code read, and leaves the JTAG TAP in its reset state.  """

    jtag.reset()
    idcode = jtag.read_dr(32)
    idcode = int(idcode)

    if idcode not in JtagIdCodes:
        raise ValueError(f"Unknown IDCODE: 0x{idcode:x}")
    print(f"Detected the IDCODE for {JtagIdCodes[idcode]}")

    jtag.reset()
    return idcode


def bypass(inp: Optional[BitSequence] = None) -> BitSequence:
    """ Move into BYPASS, send `inp`, and check for equality with what comes back. 
    Returns the resultant `BitSequence` shifted out of the device. Leaves the JTAG TAP in its reset state. 
    Note the output is shifted one bit by this function, so should be directly comparable to `inp`. 
    If no `inp` is provided, one is created internally. """

    if inp is None:
        inp = BitSequence("011011110000" * 2, length=24)

    # Reset the TAP FSM
    jtag.reset()
    jtag.change_state("shift_ir")
    # Shifting in a new IR. This also shifts out the old one.
    old_ir = jtag.shift_and_update_register(RiscvJtagRegs["BYPASS"])
    # Check that was the reset value, IDCODE
    if old_ir != RiscvJtagRegs["IDCODE"]:
        msg = f"Default/Reset IR Value {old_ir} does not match expected IDCODE {RiscvJtagRegs['IDCODE']}"
        raise ValueError(msg)

    # Move to shift in data, first via idle.
    jtag.go_idle()
    jtag.change_state("shift_dr")
    out = jtag.shift_and_update_register(inp)
    jtag.go_idle()

    # Shift the output left by one bit for comparison
    out.lsr(1)
    if out != inp:
        raise ValueError(f"Bypass failed: {inp} vs {out}")
    print(f"Bypass check passed, sent and received {out}")
    jtag.reset()
    return out


def connection_tests():
    """ Check for a valid connection, generally at startup. """

    detect_irlen()
    read_idcode()
    bypass(inp=None)


# Run connection tests at import time. Requires hardware be in place for this module to be imported.
connection_tests()

