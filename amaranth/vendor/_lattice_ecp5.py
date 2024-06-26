from abc import abstractmethod

from ..hdl import *
from ..lib import io, wiring
from ..build import *


class InnerBuffer(wiring.Component):
    """A private component used to implement ``lib.io`` buffers.

    Works like ``lib.io.Buffer``, with the following differences:

    - ``port.invert`` is ignored (handling the inversion is the outer buffer's responsibility)
    - ``t`` is per-pin inverted output enable
    """
    def __init__(self, direction, port):
        self.direction = direction
        self.port = port
        members = {}
        if direction is not io.Direction.Output:
            members["i"] = wiring.In(len(port))
        if direction is not io.Direction.Input:
            members["o"] = wiring.Out(len(port))
            members["t"] = wiring.Out(len(port))
        super().__init__(wiring.Signature(members).flip())

    def elaborate(self, platform):
        m = Module()

        if isinstance(self.port, io.SingleEndedPort):
            io_port = self.port.io
        elif isinstance(self.port, io.DifferentialPort):
            io_port = self.port.p
        else:
            raise TypeError(f"Unknown port type {self.port!r}")

        for bit in range(len(self.port)):
            name = f"buf{bit}"
            if self.direction is io.Direction.Input:
                m.submodules[name] = Instance("IB",
                    i_I=io_port[bit],
                    o_O=self.i[bit],
                )
            elif self.direction is io.Direction.Output:
                m.submodules[name] = Instance("OBZ",
                    i_T=self.t[bit],
                    i_I=self.o[bit],
                    o_O=io_port[bit],
                )
            elif self.direction is io.Direction.Bidir:
                m.submodules[name] = Instance("BB",
                    i_T=self.t[bit],
                    i_I=self.o[bit],
                    o_O=self.i[bit],
                    io_B=io_port[bit],
                )
            else:
                assert False # :nocov:

        return m


class IOBuffer(io.Buffer):
    def elaborate(self, platform):
        m = Module()

        m.submodules.buf = buf = InnerBuffer(self.direction, self.port)
        inv_mask = sum(inv << bit for bit, inv in enumerate(self.port.invert))

        if self.direction is not io.Direction.Output:
            m.d.comb += self.i.eq(buf.i ^ inv_mask)

        if self.direction is not io.Direction.Input:
            m.d.comb += buf.o.eq(self.o ^ inv_mask)
            m.d.comb += buf.t.eq(~self.oe.replicate(len(self.port)))

        return m


def _make_oereg(m, domain, oe, q):
    for bit in range(len(q)):
        m.submodules[f"oe_ff{bit}"] = Instance("OFS1P3DX",
            i_SCLK=ClockSignal(domain),
            i_SP=Const(1),
            i_CD=Const(0),
            i_D=oe,
            o_Q=q[bit],
        )


class FFBuffer(io.FFBuffer):
    def elaborate(self, platform):
        m = Module()

        m.submodules.buf = buf = InnerBuffer(self.direction, self.port)
        inv_mask = sum(inv << bit for bit, inv in enumerate(self.port.invert))

        if self.direction is not io.Direction.Output:
            i_inv = Signal.like(self.i)
            for bit in range(len(self.port)):
                m.submodules[f"i_ff{bit}"] = Instance("IFS1P3DX",
                    i_SCLK=ClockSignal(self.i_domain),
                    i_SP=Const(1),
                    i_CD=Const(0),
                    i_D=buf.i[bit],
                    o_Q=i_inv[bit],
                )
            m.d.comb += self.i.eq(i_inv ^ inv_mask)

        if self.direction is not io.Direction.Input:
            o_inv = Signal.like(self.o)
            m.d.comb += o_inv.eq(self.o ^ inv_mask)
            for bit in range(len(self.port)):
                m.submodules[f"o_ff{bit}"] = Instance("OFS1P3DX",
                    i_SCLK=ClockSignal(self.o_domain),
                    i_SP=Const(1),
                    i_CD=Const(0),
                    i_D=o_inv[bit],
                    o_Q=buf.o[bit],
                )
            _make_oereg(m, self.o_domain, ~self.oe, buf.t)

        return m


class DDRBuffer(io.DDRBuffer):
    def elaborate(self, platform):
        m = Module()

        m.submodules.buf = buf = InnerBuffer(self.direction, self.port)
        inv_mask = sum(inv << bit for bit, inv in enumerate(self.port.invert))

        if self.direction is not io.Direction.Output:
            i0_inv = Signal(len(self.port))
            i1_inv = Signal(len(self.port))
            for bit in range(len(self.port)):
                m.submodules[f"i_ddr{bit}"] = Instance("IDDRX1F",
                    i_SCLK=ClockSignal(self.i_domain),
                    i_RST=Const(0),
                    i_D=buf.i[bit],
                    o_Q0=i0_inv[bit],
                    o_Q1=i1_inv[bit],
                )
            m.d.comb += self.i[0].eq(i0_inv ^ inv_mask)
            m.d.comb += self.i[1].eq(i1_inv ^ inv_mask)

        if self.direction is not io.Direction.Input:
            o0_inv = Signal(len(self.port))
            o1_inv = Signal(len(self.port))
            m.d.comb += [
                o0_inv.eq(self.o[0] ^ inv_mask),
                o1_inv.eq(self.o[1] ^ inv_mask),
            ]
            for bit in range(len(self.port)):
                m.submodules[f"o_ddr{bit}"] = Instance("ODDRX1F",
                    i_SCLK=ClockSignal(self.o_domain),
                    i_RST=Const(0),
                    i_D0=o0_inv[bit],
                    i_D1=o1_inv[bit],
                    o_Q=buf.o[bit],
                )
            _make_oereg(m, self.o_domain, ~self.oe, buf.t)

        return m


class LatticeECP5Platform(TemplatedPlatform):
    """
    .. rubric:: Trellis toolchain

    Required tools:
        * ``yosys``
        * ``nextpnr-ecp5``
        * ``ecppack``

    The environment is populated by running the script specified in the environment variable
    ``AMARANTH_ENV_TRELLIS``, if present.

    Available overrides:
        * ``verbose``: enables logging of informational messages to standard error.
        * ``read_verilog_opts``: adds options for ``read_verilog`` Yosys command.
        * ``synth_opts``: adds options for ``synth_ecp5`` Yosys command.
        * ``script_after_read``: inserts commands after ``read_ilang`` in Yosys script.
        * ``script_after_synth``: inserts commands after ``synth_ecp5`` in Yosys script.
        * ``yosys_opts``: adds extra options for ``yosys``.
        * ``nextpnr_opts``: adds extra options for ``nextpnr-ecp5``.
        * ``ecppack_opts``: adds extra options for ``ecppack``.
        * ``add_preferences``: inserts commands at the end of the LPF file.

    Build products:
        * ``{{name}}.rpt``: Yosys log.
        * ``{{name}}.json``: synthesized RTL.
        * ``{{name}}.tim``: nextpnr log.
        * ``{{name}}.config``: ASCII bitstream.
        * ``{{name}}.bit``: binary bitstream.
        * ``{{name}}.svf``: JTAG programming vector.

    .. rubric:: Diamond toolchain

    Required tools:
        * ``pnmainc``
        * ``ddtcmd``

    The environment is populated by running the script specified in the environment variable
    ``AMARANTH_ENV_DIAMOND``, if present. On Linux, diamond_env as provided by Diamond
    itself is a good candidate. On Windows, the following script (named ``diamond_env.bat``,
    for instance) is known to work::

        @echo off
        set PATH=C:\\lscc\\diamond\\%DIAMOND_VERSION%\\bin\\nt64;%PATH%

    Available overrides:
        * ``script_project``: inserts commands before ``prj_project save`` in Tcl script.
        * ``script_after_export``: inserts commands after ``prj_run Export`` in Tcl script.
        * ``add_preferences``: inserts commands at the end of the LPF file.
        * ``add_constraints``: inserts commands at the end of the XDC file.

    Build products:
        * ``{{name}}_impl/{{name}}_impl.htm``: consolidated log.
        * ``{{name}}.bit``: binary bitstream.
        * ``{{name}}.svf``: JTAG programming vector.
    """

    toolchain = None # selected when creating platform

    device  = property(abstractmethod(lambda: None))
    package = property(abstractmethod(lambda: None))
    speed   = property(abstractmethod(lambda: None))
    grade   = "C" # [C]ommercial, [I]ndustrial

    # Trellis templates

    _nextpnr_device_options = {
        "LFE5U-12F":    "--12k",
        "LFE5U-25F":    "--25k",
        "LFE5U-45F":    "--45k",
        "LFE5U-85F":    "--85k",
        "LFE5UM-25F":   "--um-25k",
        "LFE5UM-45F":   "--um-45k",
        "LFE5UM-85F":   "--um-85k",
        "LFE5UM5G-25F": "--um5g-25k",
        "LFE5UM5G-45F": "--um5g-45k",
        "LFE5UM5G-85F": "--um5g-85k",
    }
    _nextpnr_package_options = {
        "BG256": "caBGA256",
        "MG285": "csfBGA285",
        "BG381": "caBGA381",
        "BG554": "caBGA554",
        "BG756": "caBGA756",
    }

    _trellis_required_tools = [
        "yosys",
        "nextpnr-ecp5",
        "ecppack"
    ]
    _trellis_file_templates = {
        **TemplatedPlatform.build_script_templates,
        "{{name}}.il": r"""
            # {{autogenerated}}
            {{emit_rtlil()}}
        """,
        "{{name}}.debug.v": r"""
            /* {{autogenerated}} */
            {{emit_debug_verilog()}}
        """,
        "{{name}}.ys": r"""
            # {{autogenerated}}
            {% for file in platform.iter_files(".v") -%}
                read_verilog {{get_override("read_verilog_opts")|options}} {{file}}
            {% endfor %}
            {% for file in platform.iter_files(".sv") -%}
                read_verilog -sv {{get_override("read_verilog_opts")|options}} {{file}}
            {% endfor %}
            {% for file in platform.iter_files(".il") -%}
                read_ilang {{file}}
            {% endfor %}
            read_ilang {{name}}.il
            {{get_override("script_after_read")|default("# (script_after_read placeholder)")}}
            synth_ecp5 {{get_override("synth_opts")|options}} -top {{name}}
            {{get_override("script_after_synth")|default("# (script_after_synth placeholder)")}}
            write_json {{name}}.json
        """,
        "{{name}}.lpf": r"""
            # {{autogenerated}}
            BLOCK ASYNCPATHS;
            BLOCK RESETPATHS;
            {% for port_name, pin_name, attrs in platform.iter_port_constraints_bits() -%}
                LOCATE COMP "{{port_name}}" SITE "{{pin_name}}";
                {% if attrs -%}
                IOBUF PORT "{{port_name}}"
                    {%- for key, value in attrs.items() %} {{key}}={{value}}{% endfor %};
                {% endif %}
            {% endfor %}
            {% for net_signal, port_signal, frequency in platform.iter_clock_constraints() -%}
                {% if port_signal is not none -%}
                    FREQUENCY PORT "{{port_signal.name}}" {{frequency}} HZ;
                {% else -%}
                    FREQUENCY NET "{{net_signal|hierarchy(".")}}" {{frequency}} HZ;
                {% endif %}
            {% endfor %}
            {{get_override("add_preferences")|default("# (add_preferences placeholder)")}}
        """
    }
    _trellis_command_templates = [
        r"""
        {{invoke_tool("yosys")}}
            {{quiet("-q")}}
            {{get_override("yosys_opts")|options}}
            -l {{name}}.rpt
            {{name}}.ys
        """,
        r"""
        {{invoke_tool("nextpnr-ecp5")}}
            {{quiet("--quiet")}}
            {{get_override("nextpnr_opts")|options}}
            --log {{name}}.tim
            {{platform._nextpnr_device_options[platform.device]}}
            --package {{platform._nextpnr_package_options[platform.package]|upper}}
            --speed {{platform.speed}}
            --json {{name}}.json
            --lpf {{name}}.lpf
            --textcfg {{name}}.config
        """,
        r"""
        {{invoke_tool("ecppack")}}
            {{verbose("--verbose")}}
            {{get_override("ecppack_opts")|options}}
            --input {{name}}.config
            --bit {{name}}.bit
            --svf {{name}}.svf
        """
    ]

    # Diamond templates

    _diamond_required_tools = [
        "pnmainc",
        "ddtcmd"
    ]
    _diamond_file_templates = {
        **TemplatedPlatform.build_script_templates,
        "build_{{name}}.sh": r"""
            #!/bin/sh
            # {{autogenerated}}
            set -e{{verbose("x")}}
            if [ -z "$BASH" ] ; then exec /bin/bash "$0" "$@"; fi
            if [ -n "${{platform._toolchain_env_var}}" ]; then
                bindir=$(dirname "${{platform._toolchain_env_var}}")
                . "${{platform._toolchain_env_var}}"
            fi
            {{emit_commands("sh")}}
        """,
        "{{name}}.v": r"""
            /* {{autogenerated}} */
            {{emit_verilog()}}
        """,
        "{{name}}.debug.v": r"""
            /* {{autogenerated}} */
            {{emit_debug_verilog()}}
        """,
        "{{name}}.tcl": r"""
            prj_project new -name {{name}} -impl impl -impl_dir {{name}}_impl \
                -dev {{platform.device}}-{{platform.speed}}{{platform.package}}{{platform.grade}} \
                -lpf {{name}}.lpf \
                -synthesis synplify
            {% for file in platform.iter_files(".v", ".sv", ".vhd", ".vhdl") -%}
                prj_src add {{file|tcl_quote}}
            {% endfor %}
            prj_src add {{name}}.v
            prj_impl option top {{name}}
            prj_src add {{name}}.sdc
            {{get_override("script_project")|default("# (script_project placeholder)")}}
            prj_project save
            prj_run Synthesis -impl impl
            prj_run Translate -impl impl
            prj_run Map -impl impl
            prj_run PAR -impl impl
            prj_run Export -impl impl -task Bitgen
            {{get_override("script_after_export")|default("# (script_after_export placeholder)")}}
        """,
        "{{name}}.lpf": r"""
            # {{autogenerated}}
            BLOCK ASYNCPATHS;
            BLOCK RESETPATHS;
            {% for port_name, pin_name, attrs in platform.iter_port_constraints_bits() -%}
                LOCATE COMP "{{port_name}}" SITE "{{pin_name}}";
                {% if attrs -%}
                IOBUF PORT "{{port_name}}"
                    {%- for key, value in attrs.items() %} {{key}}={{value}}{% endfor %};
                {% endif %}
            {% endfor %}
            {{get_override("add_preferences")|default("# (add_preferences placeholder)")}}
        """,
        "{{name}}.sdc": r"""
            set_hierarchy_separator {/}
            {% for net_signal, port_signal, frequency in platform.iter_clock_constraints() -%}
                {% if port_signal is not none -%}
                    create_clock -name {{port_signal.name|tcl_quote}} -period {{1000000000/frequency}} [get_ports {{port_signal.name|tcl_quote}}]
                {% else -%}
                    create_clock -name {{net_signal.name|tcl_quote}} -period {{1000000000/frequency}} [get_nets {{net_signal|hierarchy("/")|tcl_quote}}]
                {% endif %}
            {% endfor %}
            {{get_override("add_constraints")|default("# (add_constraints placeholder)")}}
        """,
    }
    _diamond_command_templates = [
        # These don't have any usable command-line option overrides.
        r"""
        {{invoke_tool("pnmainc")}}
            {{name}}.tcl
        """,
        r"""
        {{invoke_tool("ddtcmd")}}
            -oft -bit
            -if {{name}}_impl/{{name}}_impl.bit -of {{name}}.bit
        """,
        r"""
        {{invoke_tool("ddtcmd")}}
            -oft -svfsingle -revd -op "Fast Program"
            -if {{name}}_impl/{{name}}_impl.bit -of {{name}}.svf
        """,
    ]

    # Common logic

    def __init__(self, *, toolchain="Trellis"):
        super().__init__()

        assert toolchain in ("Trellis", "Diamond")
        self.toolchain = toolchain

    @property
    def required_tools(self):
        if self.toolchain == "Trellis":
            return self._trellis_required_tools
        if self.toolchain == "Diamond":
            return self._diamond_required_tools
        assert False

    @property
    def file_templates(self):
        if self.toolchain == "Trellis":
            return self._trellis_file_templates
        if self.toolchain == "Diamond":
            return self._diamond_file_templates
        assert False

    @property
    def command_templates(self):
        if self.toolchain == "Trellis":
            return self._trellis_command_templates
        if self.toolchain == "Diamond":
            return self._diamond_command_templates
        assert False

    @property
    def default_clk_constraint(self):
        if self.default_clk == "OSCG":
            return Clock(310e6 / self.oscg_div)
        return super().default_clk_constraint

    def create_missing_domain(self, name):
        # Lattice ECP5 devices have two global set/reset signals: PUR, which is driven at startup
        # by the configuration logic and unconditionally resets every storage element, and GSR,
        # which is driven by user logic and each storage element may be configured as affected or
        # unaffected by GSR. PUR is purely asynchronous, so even though it is a low-skew global
        # network, its deassertion may violate a setup/hold constraint with relation to a user
        # clock. To avoid this, a GSR/SGSR instance should be driven synchronized to user clock.
        if name == "sync" and self.default_clk is not None:
            m = Module()
            if self.default_clk == "OSCG":
                if not hasattr(self, "oscg_div"):
                    raise ValueError("OSCG divider (oscg_div) must be an integer between 2 "
                                     "and 128")
                if not isinstance(self.oscg_div, int) or self.oscg_div < 2 or self.oscg_div > 128:
                    raise ValueError("OSCG divider (oscg_div) must be an integer between 2 "
                                     "and 128, not {!r}"
                                     .format(self.oscg_div))
                clk_i = Signal()
                m.submodules += Instance("OSCG", p_DIV=self.oscg_div, o_OSC=clk_i)
            else:
                clk_i = self.request(self.default_clk).i
            if self.default_rst is not None:
                rst_i = self.request(self.default_rst).i
            else:
                rst_i = Const(0)

            gsr0 = Signal()
            gsr1 = Signal()
            # There is no end-of-startup signal on ECP5, but PUR is released after IOB enable, so
            # a simple reset synchronizer (with PUR as the asynchronous reset) does the job.
            m.submodules += [
                Instance("FD1S3AX", p_GSR="DISABLED", i_CK=clk_i, i_D=~rst_i, o_Q=gsr0),
                Instance("FD1S3AX", p_GSR="DISABLED", i_CK=clk_i, i_D=gsr0,   o_Q=gsr1),
                # Although we already synchronize the reset input to user clock, SGSR has dedicated
                # clock routing to the center of the FPGA; use that just in case it turns out to be
                # more reliable. (None of this is documented.)
                Instance("SGSR", i_CLK=clk_i, i_GSR=gsr1),
            ]
            # GSR implicitly connects to every appropriate storage element. As such, the sync
            # domain is reset-less; domains driven by other clocks would need to have dedicated
            # reset circuitry or otherwise meet setup/hold constraints on their own.
            m.domains += ClockDomain("sync", reset_less=True)
            m.d.comb += ClockSignal("sync").eq(clk_i)
            return m

    def get_io_buffer(self, buffer):
        if isinstance(buffer, io.Buffer):
            result = IOBuffer(buffer.direction, buffer.port)
        elif isinstance(buffer, io.FFBuffer):
            result = FFBuffer(buffer.direction, buffer.port)
        elif isinstance(buffer, io.DDRBuffer):
            result = DDRBuffer(buffer.direction, buffer.port)
        else:
            raise TypeError(f"Unsupported buffer type {buffer!r}") # :nocov:
        if buffer.direction is not io.Direction.Output:
            result.i = buffer.i
        if buffer.direction is not io.Direction.Input:
            result.o = buffer.o
            result.oe = buffer.oe
        return result

    # CDC primitives are not currently specialized for ECP5.
    # While Diamond supports false path constraints; nextpnr-ecp5 does not.
