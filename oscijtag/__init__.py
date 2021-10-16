"""
# OsciBear JTAG Access

Via `pyftdi`, the FTDI USB-JTAG chip, and the Olimex ARM-USB-TINY-H adapter which uses it. 

Adapted from PyFTDI's JTAG unit-test: 
https://github.com/eblot/pyftdi/blob/master/pyftdi/tests/jtag.py

This module defines several free-functions which execute common RISC-V JTAG commands, 
such as `read_dtmcontrol`, `bypass`, and `read_idcode`. 
More direct access to the underlying `pyftdi.JtagEngine` is avalable via the module-level `jtag` attribute. 

This module is designed to be used as a library for larger test programs and scripts. 
Quick tests of its installation and associated hardware setup are available via its `check_connection` function, as in: 
```shell
python -c "import oscijtag; oscijtag.check_connection()"
```
The `check_connection` method is also recommended to be run early in such test-programs. 

"""

__version__ = "0.1.0"

from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Union
from types import SimpleNamespace

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
RiscvJtagRegs = SimpleNamespace(
    # BYPASS is also available at reserved addresses 0x12 through 0x1F
    BYPASS=BitSequence("00000", msb=True, length=5),
    IDCODE=BitSequence("00001", msb=True, length=5),
    DTMCS=BitSequence("10000", msb=True, length=5),
    DMI=BitSequence("10001", msb=True, length=5),
)


""" 
Enumerated, Known-Good JTAG IDCODE Values. 
Keys are integer code-values, and values are a string description of the device.
"""
JtagIdCodes = {
    0x00000001: "DEFAULT",  # Default ID
    0x20000913: "SIFIVE",  # SiFive FE310, as on the SparkFun Red-V Board
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

    jtag.reset()
    return irlen


def read_idcode(from_reset: bool = True) -> int:
    """ Read the default data-register, IDCODE. 
    Check for existence in our know-good values dict. 
    Returns the integer id-code read, and leaves the JTAG TAP in its reset state.  

    Boolean argument `from_reset` indicates whether to send the `IDCODE` IR, 
    or to read the DR directly from the default/ reset state (which should be the IDCODE). """

    jtag.reset()
    if not from_reset:
        jtag.write_ir(RiscvJtagRegs.IDCODE)
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

    if inp is None:  # Create some default data
        inp = BitSequence("011011110000" * 2, length=24)

    # Reset the TAP FSM
    jtag.reset()

    # Write the instruction register
    jtag.write_ir(RiscvJtagRegs.BYPASS)

    # Move to shift in data, first via run-test-idle.
    jtag.go_idle()
    jtag.change_state("shift_dr")
    out = jtag.shift_and_update_register(inp)

    # Shift the output left by one bit for comparison
    out.lsr(1)
    if out != inp:
        raise ValueError(f"Bypass failed: {inp} vs {out}")
    print(f"Bypass check passed, sent and received {out}")

    jtag.reset()
    return out


@dataclass
class DtmControlValue:
    """ Field-Decoded `dtmcontrol` Register Value """

    version: int
    abits: int
    dmistat: int
    idle: int
    dmireset: int
    dmihardreset: int

    @classmethod
    def from_bitseq(cls, bitseq: BitSequence) -> "DtmControlValue":
        """ Decode from a `BitSequence` """
        val = int(bitseq)

        if (val >> 15) & 0x1 != 0:
            msg = f"Invalid DTMCONTROL bit 15 high value, should be hard-coded low "
            raise ValueError(msg)
        if (val >> 18) != 0:
            msg = f"Invalid DTMCONTROL bits 18-31: {val >> 18}, should be zero "
            raise ValueError(msg)

        return DtmControlValue(
            version=val & 0x0F,  # Bottom 4 bits
            abits=(val >> 4) & 0x3F,  # 6 bits
            dmistat=(val >> 10) & 0x3,  # 2 bits
            idle=(val >> 12) & 0x7,  # 3 bits
            dmireset=(val >> 16) & 0x1,  # 1 bit
            dmihardreset=(val >> 17) & 0x1,  # 1 bit
        )


def read_dtmcontrol() -> Tuple[int, DtmControlValue]:
    """ Read the `dtmcs` (AKA `dtmcontrol`) register. Returns its integer and decoded values. """

    # Reset the TAP FSM
    jtag.reset()
    # Write the instruction register
    jtag.write_ir(RiscvJtagRegs.DTMCS)

    # Move to shift in data, first via run-test-idle.
    jtag.go_idle()
    jtag.change_state("shift_dr")
    inp = BitSequence(0, length=32)
    out = jtag.shift_and_update_register(inp)

    # Decode and return what comes back
    rv = int(out), DtmControlValue.from_bitseq(out)
    print(f"Read DtmControl: {hex(rv[0])} => {rv[1]}")

    jtag.reset()
    return rv


@dataclass
class DmiValue:
    """ Field-Decoded `dmi` Register Value """

    # Register length
    len: int

    # Register fields
    address: int
    data: int
    op: int

    def to_bitseq(self) -> BitSequence:
        """ Encode to a `BitSequence` """
        val = (
            (self.op & 0x03) | ((self.data << 2) & 0x3_FFFF_FFFC) | (self.address << 34)
        )
        return BitSequence(val, length=self.len)

    @classmethod
    def from_bitseq(cls, bitseq: BitSequence) -> "DmiValue":
        """ Decode from a `BitSequence`. Length is kept identical to that of `bitseq`. """
        val = int(bitseq)

        return DmiValue(
            len=len(bitseq),
            op=val & 0x03,  # Bottom 2 bits
            data=(val >> 2) & 0xFFFF_FFFF,  # 32 bits
            address=val >> 34,  # Remaining `abits` bits
        )


def read_dmi(abits: int) -> Tuple[int, DmiValue]:
    """ Read the `dmi` Debug-Module Inteface register. 
    DMI is of width `33 + abits`, where `abits` is the address-bits field read from `dtmcontrol`. """

    # Reset the TAP FSM
    jtag.reset()
    # Write the instruction register
    jtag.write_ir(RiscvJtagRegs.DMI)

    # Move to shift in data, first via run-test-idle.
    jtag.go_idle()
    jtag.change_state("shift_dr")
    inp = BitSequence(0, length=abits + 33)
    out = jtag.shift_and_update_register(inp)

    # Decode and return what comes back
    rv = int(out), DmiValue.from_bitseq(out)
    print(f"Read Dmi: {hex(rv[0])} => {rv[1]}")

    jtag.reset()
    return rv


def write_dmi(data: Union[DmiValue, BitSequence]) -> Tuple[int, DmiValue]:
    """ Write the `dmi` Debug-Module Inteface register. 
    Sends input of `data`'s width, which must equal that of `dmi` for writes to succeed. """

    # Reset the TAP FSM
    jtag.reset()
    # Write the instruction register
    jtag.write_ir(RiscvJtagRegs.DMI)

    # Move to shift in data, first via run-test-idle.
    jtag.go_idle()
    jtag.change_state("shift_dr")

    if isinstance(data, DmiValue):
        data = data.to_bitseq()
    out = jtag.shift_and_update_register(data)

    # Decode and return what comes back
    rv = int(out), DmiValue.from_bitseq(out)
    print(f"Wrote Dmi, Got Back: {hex(rv[0])} => {rv[1]}")

    jtag.reset()
    return rv


def check_connection():
    """ Check for a valid connection. 
    Typically to be performed at startup, before attempting MMIOs and other more elaborate commands. """

    print("Checking Connection")

    print("Detecting IR Length")
    detect_irlen()

    print("Reading the reset-value data-register (IDCODE)")
    read_idcode(from_reset=True)

    print("Reading IDCODE")
    read_idcode(from_reset=False)

    print("Testing BYPASS")
    bypass(inp=None)

    print("Reading DTMCONTROL")
    (_, dtmctrl) = read_dtmcontrol()

    print("Reading DMI")
    read_dmi(dtmctrl.abits)

    # Make a (thus far nonsensical) debug-module request via `dmi`
    # dmival = DmiValue(len=33 + dtmctrl.abits, op=1, data=0xFFFF_FFFF, address=0x7F,)
    # write_dmi(dmival)

    print("Connection Checks Succeeded")


# Run connection tests at import time. Requires hardware be in place for this module to be imported.
# check_connection()

