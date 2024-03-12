
from abc import abstractproperty

from ..hdl import *
from ..build import *

__all__ = ["LatticeNexusPlatform"]

class LatticeNexusPlatform(TemplatedPlatform):
    """
    .. rubric:: Oxide toolchain

    Required tools:
        * ``yosys``
        * ``nextpnr-nexus``
        * ``prjoxide``

    FIXME The environment is populated by running the script specified in the environment variable
    ``AMARANTH_ENV_OXIDE``, if present.

    Available overrides:
        * ``verbose``: enables logging of informational messages to standard error.
        * ``read_verilog_opts``: adds options for ``read_verilog`` Yosys command.
        * ``synth_opts``: adds options for ``synth_nexus`` Yosys command.
        * ``script_after_read``: inserts commands after ``read_ilang`` in Yosys script.
        * ``script_after_synth``: inserts commands after ``synth_nexus`` in Yosys script.
        * ``yosys_opts``: adds extra options for ``yosys``.
        * ``nextpnr_opts``: adds extra options for ``nextpnr-nexus``.
        * ``prjoxide_opts``: adds extra options for ``prjoxide``.
        * ``add_preferences``: inserts commands at the end of the LPF file.

    Build products:
        * ``{{name}}.rpt``: Yosys log.
        * ``{{name}}.json``: synthesized RTL.
        * ``{{name}}.tim``: nextpnr log.
        * ``{{name}}.config``: ASCII bitstream.
        * ``{{name}}.bit``: binary bitstream.
        * ``{{name}}.xcf``: JTAG programming vector.

    .. rubric:: Radiant toolchain

    Required tools:
        * ``yosys`` # optional
        * ``radiantc``
        * ``programmer`` # optional

    The environment is populated by running the script specified in the environment variable
    ``AMARANTH_ENV_RADIANT``, if present. On Linux, radiant_env as provided by Radiant
    itself is a good candidate. On Windows, the following script (named ``radiant_env.bat``,
    for instance) is known to work::

        @echo off
        set PATH=C:\\lscc\\radiant\\%RADIANT_VERSION%\\bin\\nt64;%PATH%

    Available overrides:
        * ``script_project``: inserts commands before ``prj_save`` in Tcl script.
        * ``script_after_export``: inserts commands after ``prj_run Export`` in Tcl script.
        * ``add_constraints``: inserts commands at the end of the SDC file.
        * ``add_preferences``: inserts commands at the end of the PDC file.

    Build products:
        * ``{{name}}_impl/{{name}}_impl.htm``: consolidated log.
        * ``{{name}}.bit``: binary bitstream.
        * ``{{name}}.xcf``: JTAG programming vector. (if using ``programmer``)
    """

    toolchain = None # selected when creating platform

    device  = abstractproperty()
    package = abstractproperty()
    speed   = abstractproperty()
    grade   = "C" # [C]ommercial, [I]ndustrial

    # Oxide templates

    _nextpnr_device_options = { # TODO: Add Certus-NX devices
        "LIFCL-40":    "--40k",
        "LIFCL-17":    "--17k",
    }

    _nextpnr_package_options = { # TODO: Add Certus-NX packages
        "SG72": "QFN72",
        "UWG72": "WLCSP72",
        "MG121": "csfBGA121",
        "BG196": "caBGA196",
        "BG256": "caBGA256",
        "MG289": "csBGA289",
        "BG400": "caBGA400",
    }

    _oxide_required_tools = [ 
        "yosys",
        "nextpnr-nexus",
        "prjoxide"
    ]
    _oxide_file_templates = {
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
            delete w:$verilog_initial_trigger
            {{get_override("script_after_read")|default("# (script_after_read placeholder)")}}
            synth_nexus {{get_override("synth_opts")|options}} -top {{name}}
            {{get_override("script_after_synth")|default("# (script_after_synth placeholder)")}}
            write_json {{name}}.json
        """,
        "{{name}}.pdc": r"""
            # {{autogenerated}}
            {% for port_name, pin_name, attrs in platform.iter_port_constraints_bits() -%}
                ldc_set_location -site {{ '{' }}{{pin_name}}{{ '}' }} {{'['}}get_ports {{port_name}}{{']'}} 
                {% if attrs -%}
                ldc_set_port -iobuf {{ '{' }}{%- for key, value in attrs.items() %}{{key}}={{value}} {% endfor %}{{ '}' }} {{'['}}get_ports {{port_name}}{{']'}}
                {% endif %}
            {% endfor %}
            {% for net_signal, port_signal, frequency in platform.iter_clock_constraints() -%}
            {#
                {% if port_signal is not none -%}
                    set_frequency "{{port_signal.name}}" {{frequency/1000000}};
                {% else -%}
                    set_frequency "{{net_signal|hierarchy(".")}}" {{frequency}} HZ;
                {% endif %}
            #}
            {% endfor %}
            {{get_override("add_preferences")|default("# (add_preferences placeholder)")}}
        """
    }
    _oxide_command_templates = [
        r"""
        {{invoke_tool("yosys")}}
            {{get_override("yosys_opts")|options}}
            -l {{name}}.rpt
            {{name}}.ys
        """,
        r"""
        {{invoke_tool("nextpnr-nexus")}}
            {{get_override("nextpnr_opts")|options}}
            --log {{name}}.tim
            --device {{platform.device}}-{{platform.speed}}{{platform.package}}{{platform.grade}}            
            --pdc {{name}}.pdc
            --json {{name}}.json
            --fasm {{name}}.fasm
        """,
        r"""
        {{invoke_tool("prjoxide")}}
            {# {{verbose("--verbose")}} #}
            {{get_override("prjoxide_opts")|options}}
            pack {{name}}.fasm
            {{name}}.bit
        """
    ]

    # Radiant templates

    _radiant_required_tools = [
        "radiantc",
    ]
    _radiant_file_templates = {
        **TemplatedPlatform.build_script_templates,
        "build_{{name}}.sh": r"""
            # {{autogenerated}}
            set -e{{verbose("x")}}
            if [ -z "$BASH" ] ; then exec /bin/bash "$0" "$@"; fi
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
            prj_create -name {{name}} -impl impl \
                -dev {{platform.device}}-{{platform.speed}}{{platform.package}}{{platform.grade}} \
                -synthesis synplify
            {% for file in platform.iter_files(".v", ".sv", ".vhd", ".vhdl") -%}
                prj_add_source {{file|tcl_quote}}
            {% endfor %}
            prj_add_source {{name}}.v
            prj_add_source {{name}}.sdc
            prj_add_source {{name}}.pdc
            prj_set_impl_opt top \"{{name}}\"
            {{get_override("script_project")|default("# (script_project placeholder)")}}
            prj_save
            prj_run Synthesis -impl impl -forceOne
            prj_run Map -impl impl
            prj_run PAR -impl impl
            prj_run Export -impl impl -task Bitgen
            {{get_override("script_after_export")|default("# (script_after_export placeholder)")}}
        """,
        # Pre-synthesis SDC constraints
        "{{name}}.sdc": r"""
            {% for net_signal, port_signal, frequency in platform.iter_clock_constraints() -%}
                {% if port_signal is not none -%}
                    create_clock -name {{port_signal.name|tcl_quote}} -period {{1000000000/frequency}} [get_ports {{port_signal.name}}]
                {% else -%}
                    create_clock -name {{net_signal.name|tcl_quote}} -period {{1000000000/frequency}} [get_nets {{net_signal|hierarchy("/")}}]
                {% endif %}
            {% endfor %}
            {{get_override("add_constraints")|default("# (add_constraints placeholder)")}}
        """,
        # Physical PDC contraints
        "{{name}}.pdc": r"""
            {% for port_name, pin_name, attrs in platform.iter_port_constraints_bits() -%}
                ldc_set_location -site "{{pin_name}}" [get_ports {{port_name|tcl_quote}}]
                {% if attrs -%}
                ldc_set_port -iobuf { {%- for key, value in attrs.items() %} {{key}}={{value}}{% endfor %} } [get_ports {{port_name|tcl_quote}}]
                {% endif %}
            {% endfor %}
            {{get_override("add_preferences")|default("# (add_preferences placeholder)")}}
        """,
    }
    _radiant_command_templates = [
        # These don't have any usable command-line option overrides.
        r"""
        {{invoke_tool("radiantc")}}
            {{name}}.tcl
        """,
        ## TODO: FIXME
        #r"""
        #{{invoke_tool("programmer")}}
        #    -oft -bit
        #    -if {{name}}_impl/{{name}}_impl.bit -of {{name}}.bit
        #""",
        #r"""
        #{{invoke_tool("programmer")}}
        #    -oft -xcfsingle -revd -op "Fast Program"
        #    -if {{name}}_impl/{{name}}_impl.bit -of {{name}}.xcf
        #""",
    ]

    # Common logic

    def __init__(self, *, toolchain="Oxide"):
        super().__init__()

        assert toolchain in ("Oxide", "Radiant")
        self.toolchain = toolchain

    @property
    def required_tools(self):
        if self.toolchain == "Oxide":
            return self._oxide_required_tools
        if self.toolchain == "Radiant":
            return self._radiant_required_tools
        assert False

    @property
    def file_templates(self):
        if self.toolchain == "Oxide":
            return self._oxide_file_templates
        if self.toolchain == "Radiant":
            return self._radiant_file_templates
        assert False

    @property
    def command_templates(self):
        if self.toolchain == "Oxide":
            return self._oxide_command_templates
        if self.toolchain == "Radiant":
            return self._radiant_command_templates
        assert False

    @property
    def default_clk_constraint(self):
        if self.default_clk == "OSCA":
            return Clock(450e6 / self.osca_div)
        return super().default_clk_constraint

    def create_missing_domain(self, name):
        # Lattice Nexus devices have two global set/reset signals: PUR, which is driven at startup
        # by the configuration logic and unconditionally resets every storage element, and GSR,
        # which is driven by user logic and each storage element may be configured as affected or
        # unaffected by GSR. PUR is purely asynchronous, so even though it is a low-skew global
        # network, its deassertion may violate a setup/hold constraint with relation to a user
        # clock. To avoid this, we use a GSR instance configured to release at the positive edge
        # of the user clock
        if name == "sync" and self.default_clk is not None:
            m = Module()
            if self.default_clk == "OSCA":
                if not hasattr(self, "osca_div"):
                    raise ValueError(
                        "OSCA divider (osca_div) must be an integer between 2 "
                        "and 256"
                    )
                if (
                    not isinstance(self.osca_div, int)
                    or self.osca_div < 2
                    or self.osca_div > 256
                ):
                    raise ValueError(
                        "OSCA divider (osca_div) must be an integer between 2 "
                        "and 256, not {!r}".format(self.osca_div)
                    )
                clk_i = Signal()
                m.submodules += Instance(
                    "OSCA",
                    p_HF_CLK_DIV=str(self.osca_div - 1),
                    i_HFOUTEN=Const(1),
                    i_HFSDSCEN=Const(0),  # HFSDSCEN used for SED/SEC detector
                    o_HFCLKOUT=clk_i,
                )
            else:
                clk_i = self.request(self.default_clk).i

            if self.default_rst is not None:
                rst_i = self.request(self.default_rst).i
            else:
                rst_i = Const(0)

            gsr0 = Signal()
            gsr1 = Signal()
            # On Nexus all the D-type FFs have either an synchronous or asynchronous preset. Here
            # we build a simple reset synchronizer from D-type FFs with a positive-level
            # asynchronous preset which we tie low
            m.submodules += [
                Instance(
                    "FD1P3BX",
                    p_GSR="DISABLED",
                    i_CK=clk_i,
                    i_D=~rst_i,
                    i_SP=Const(1),
                    i_PD=Const(0),
                    o_Q=gsr0,
                ),
                Instance(
                    "FD1P3BX",
                    p_GSR="DISABLED",
                    i_CK=clk_i,
                    i_D=gsr0,
                    i_SP=Const(1),
                    i_PD=Const(0),
                    o_Q=gsr1,
                ),
                Instance("GSR", p_SYNCMODE="SYNC", i_CLK=clk_i, i_GSR_N=gsr1),
            ]
            # GSR implicitly connects to every appropriate storage element. As such, the sync
            # domain is reset-less; domains driven by other clocks would need to have dedicated
            # reset circuitry or otherwise meet setup/hold constraints on their own.
            m.domains += ClockDomain("sync", reset_less=True)
            m.d.comb += ClockSignal("sync").eq(clk_i)
            return m

    # pg. 17 of FPGA-TN-02067-1-8-sysIO-User-Guide-Nexus-Platform.pdf
    _single_ended_io_types = [
        "LVCMOS33", "LVTTL33", 
        "LVCMOS25", 
        "LVCMOS18", "LVCMOS18H",
        "LVCMOS15", "LVCMOS15H",  
        "LVCMOS12", "LVCMOS12H", 
        "LVCMOS10", "LVCMOS10H", "LVCMOS10R", 
        "SSTL15_I", "SSTL15_II",
        "SSTL135_I", "SSTL135_II", 
        "HSTL15_I", 
        "HSUL12",
    ]
    _differential_io_types = [
        "LVCMOS33D", "LVTTL33D",
        "LVCMOS25D", 
        "SSTL15D_I", "SSTL15D_II",
        "SSTL135D_I", "SSTL135D_II", 
        "HSTL15D_I", 
        "HSUL12D",
        "LVDS", "LVDSE", "SUBLVDS", "SUBLVDSEH", 
        "SLVS", 
        "MIPI_DPHY", 
    ]

    def should_skip_port_component(self, port, attrs, component):
        # On Nexus a differential IO is placed by only instantiating an IO buffer primitive at
        # the PIOA or PIOC location, which is always the non-inverting pin.
        if (
            attrs.get("IO_TYPE", "LVCMOS25") in self._differential_io_types
            and component == "n"
        ):
            return True
        return False

    def _get_xdr_buffer(self, m, pin, *, i_invert=False, o_invert=False):
        def get_ireg(clk, d, q):
            for bit in range(len(q)):
                m.submodules += Instance("IFD1P3DX",
                    i_CK=clk,
                    i_SP=Const(1),
                    i_CD=Const(0),
                    i_D=d[bit],
                    o_Q=q[bit],
                )

        def get_oreg(clk, d, q):
            for bit in range(len(q)):
                m.submodules += Instance("OFD1P3DX",
                    i_CK=clk,
                    i_SP=Const(1),
                    i_CD=Const(0),
                    i_D=d[bit],
                    o_Q=q[bit],
                )

        def get_oereg(clk, oe, q):
            for bit in range(len(q)):
                m.submodules += Instance("OFD1P3DX",
                    i_CK=clk,
                    i_SP=Const(1),
                    i_CD=Const(0),
                    i_D=oe,
                    o_Q=q[bit],
                )

        def get_iddr(sclk, d, q0, q1):
            for bit in range(len(d)):
                m.submodules += Instance("IDDRX1",
                    i_SCLK=sclk,
                    i_RST=Const(0),
                    i_D=d[bit],
                    o_Q0=q0[bit],
                    o_Q1=q1[bit],
                    #p_GSR="DISABLED",
                )

        def get_iddrx2(sclk, eclk, d, q0, q1, q2, q3):
            for bit in range(len(d)):
                m.submodules += Instance("IDDRX2",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_ALIGNWD=Const(0),
                    i_D=d[bit],
                    o_Q0=q0[bit],
                    o_Q1=q1[bit],
                    o_Q2=q2[bit],
                    o_Q3=q3[bit],
                )

        def get_iddr71(sclk, eclk, d, q0, q1, q2, q3, q4, q5, q6):
            for bit in range(len(d)):
                m.submodules += Instance("IDDR71",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_D=d[bit],
                    o_Q0=q0[bit],
                    o_Q1=q1[bit],
                    o_Q2=q2[bit],
                    o_Q3=q3[bit],
                    o_Q4=q4[bit],
                    o_Q5=q5[bit],
                    o_Q6=q6[bit],
                    #p_GSR="DISABLED",
                )

        def get_iddrx4(sclk, eclk, d, q0, q1, q2, q3, q4, q5, q6, q7):
            for bit in range(len(d)):
                m.submodules += Instance("IDDRX4",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_ALIGNWD=Const(0),
                    i_D=d[bit],
                    o_Q0=q0[bit],
                    o_Q1=q1[bit],
                    o_Q2=q2[bit],
                    o_Q3=q3[bit],
                    o_Q4=q4[bit],
                    o_Q5=q5[bit],
                    o_Q6=q6[bit],
                    o_Q7=q7[bit],
                )

        def get_iddrx5(sclk, eclk, d, q0, q1, q2, q3, q4, q5, q6, q7, q8, q9):
            for bit in range(len(d)):
                m.submodules += Instance("IDDRX5",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_ALIGNWD=Const(0),
                    i_D=d[bit],
                    o_Q0=q0[bit],
                    o_Q1=q1[bit],
                    o_Q2=q2[bit],
                    o_Q3=q3[bit],
                    o_Q4=q4[bit],
                    o_Q5=q5[bit],
                    o_Q6=q6[bit],
                    o_Q7=q7[bit],
                    o_Q8=q8[bit],
                    o_Q9=q9[bit],
                )

        def get_oddr(sclk, d0, d1, q):
            for bit in range(len(q)):
                m.submodules += Instance("ODDRX1",
                    i_SCLK=sclk,
                    i_RST=Const(0),
                    i_D0=d0[bit],
                    i_D1=d1[bit],
                    o_Q=q[bit],
                )

        def get_oddrx2(sclk, eclk, d0, d1, d2, d3, q):
            for bit in range(len(q)):
                m.submodules += Instance("ODDRX2",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_D0=d0[bit],
                    i_D1=d1[bit],
                    i_D2=d2[bit],
                    i_D3=d3[bit],
                    o_Q=q[bit],
                )

        def get_oddr71b(sclk, eclk, d0, d1, d2, d3, d4, d5, d6, q):
            for bit in range(len(q)):
                m.submodules += Instance("ODDR71",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_D0=d0[bit],
                    i_D1=d1[bit],
                    i_D2=d2[bit],
                    i_D3=d3[bit],
                    i_D4=d4[bit],
                    i_D5=d5[bit],
                    i_D6=d6[bit],
                    o_Q=q[bit],
                )

        def get_oddrx4(sclk, eclk, d0, d1, d2, d3, d4, d5, d6, d7, q):
            for bit in range(len(d)):
                m.submodules += Instance("ODDRX4",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_D0=d0[bit],
                    i_D1=d1[bit],
                    i_D2=d2[bit],
                    i_D3=d3[bit],
                    i_D4=d4[bit],
                    i_D5=d5[bit],
                    i_D6=d6[bit],
                    i_D7=d7[bit],
                    o_Q=q[bit],
                )

        def get_oddrx5(sclk, eclk, d0, d1, d2, d3, d4, d5, d6, d7, d8, d9, q):
            for bit in range(len(d)):
                m.submodules += Instance("ODDRX5",
                    i_SCLK=sclk,
                    i_ECLK=eclk,
                    i_RST=Const(0),
                    i_D0=d0[bit],
                    i_D1=d1[bit],
                    i_D2=d2[bit],
                    i_D3=d3[bit],
                    i_D4=d4[bit],
                    i_D5=d5[bit],
                    i_D6=d6[bit],
                    i_D7=d7[bit],
                    i_D8=d8[bit],
                    i_D9=d9[bit],
                    o_Q=q[bit],
                )

        def get_ineg(z, invert):
            if invert:
                a = Signal.like(z, name_suffix="_n")
                m.d.comb += z.eq(~a)
                return a
            else:
                return z

        def get_oneg(a, invert):
            if invert:
                z = Signal.like(a, name_suffix="_n")
                m.d.comb += z.eq(~a)
                return z
            else:
                return a

        if "i" in pin.dir:
            if pin.xdr < 2:
                pin_i = get_ineg(pin.i, i_invert)
            elif pin.xdr == 2:
                pin_i0 = get_ineg(pin.i0, i_invert)
                pin_i1 = get_ineg(pin.i1, i_invert)
            elif pin.xdr == 4:
                pin_i0 = get_ineg(pin.i0, i_invert)
                pin_i1 = get_ineg(pin.i1, i_invert)
                pin_i2 = get_ineg(pin.i2, i_invert)
                pin_i3 = get_ineg(pin.i3, i_invert)
            elif pin.xdr == 7:
                pin_i0 = get_ineg(pin.i0, i_invert)
                pin_i1 = get_ineg(pin.i1, i_invert)
                pin_i2 = get_ineg(pin.i2, i_invert)
                pin_i3 = get_ineg(pin.i3, i_invert)
                pin_i4 = get_ineg(pin.i4, i_invert)
                pin_i5 = get_ineg(pin.i5, i_invert)
                pin_i6 = get_ineg(pin.i6, i_invert)
            elif pin.xdr == 8:
                pin_i0 = get_ineg(pin.i0, i_invert)
                pin_i1 = get_ineg(pin.i1, i_invert)
                pin_i2 = get_ineg(pin.i2, i_invert)
                pin_i3 = get_ineg(pin.i3, i_invert)
                pin_i4 = get_ineg(pin.i4, i_invert)
                pin_i5 = get_ineg(pin.i5, i_invert)
                pin_i6 = get_ineg(pin.i6, i_invert)
                pin_i7 = get_ineg(pin.i7, i_invert)
            elif pin.xdr == 10:
                pin_i0 = get_ineg(pin.i0, i_invert)
                pin_i1 = get_ineg(pin.i1, i_invert)
                pin_i2 = get_ineg(pin.i2, i_invert)
                pin_i3 = get_ineg(pin.i3, i_invert)
                pin_i4 = get_ineg(pin.i4, i_invert)
                pin_i5 = get_ineg(pin.i5, i_invert)
                pin_i6 = get_ineg(pin.i6, i_invert)
                pin_i7 = get_ineg(pin.i7, i_invert)
                pin_i8 = get_ineg(pin.i8, i_invert)
                pin_i9 = get_ineg(pin.i9, i_invert)
        if "o" in pin.dir:
            if pin.xdr < 2:
                pin_o = get_oneg(pin.o, o_invert)
            elif pin.xdr == 2:
                pin_o0 = get_oneg(pin.o0, o_invert)
                pin_o1 = get_oneg(pin.o1, o_invert)
            elif pin.xdr == 4:
                pin_o0 = get_oneg(pin.o0, o_invert)
                pin_o1 = get_oneg(pin.o1, o_invert)
                pin_o2 = get_oneg(pin.o2, o_invert)
                pin_o3 = get_oneg(pin.o3, o_invert)
            elif pin.xdr == 7:
                pin_o0 = get_oneg(pin.o0, o_invert)
                pin_o1 = get_oneg(pin.o1, o_invert)
                pin_o2 = get_oneg(pin.o2, o_invert)
                pin_o3 = get_oneg(pin.o3, o_invert)
                pin_o4 = get_oneg(pin.o4, o_invert)
                pin_o5 = get_oneg(pin.o5, o_invert)
                pin_o6 = get_oneg(pin.o6, o_invert)
            elif pin.xdr == 8:
                pin_o0 = get_oneg(pin.o0, o_invert)
                pin_o1 = get_oneg(pin.o1, o_invert)
                pin_o2 = get_oneg(pin.o2, o_invert)
                pin_o3 = get_oneg(pin.o3, o_invert)
                pin_o4 = get_oneg(pin.o4, o_invert)
                pin_o5 = get_oneg(pin.o5, o_invert)
                pin_o6 = get_oneg(pin.o6, o_invert)
                pin_o7 = get_oneg(pin.o7, o_invert)
            elif pin.xdr == 10:
                pin_o0 = get_oneg(pin.o0, o_invert)
                pin_o1 = get_oneg(pin.o1, o_invert)
                pin_o2 = get_oneg(pin.o2, o_invert)
                pin_o3 = get_oneg(pin.o3, o_invert)
                pin_o4 = get_oneg(pin.o4, o_invert)
                pin_o5 = get_oneg(pin.o5, o_invert)
                pin_o6 = get_oneg(pin.o6, o_invert)
                pin_o7 = get_oneg(pin.o7, o_invert)
                pin_o8 = get_oneg(pin.o8, o_invert)
                pin_o9 = get_oneg(pin.o9, o_invert)

        i = o = t = None
        if "i" in pin.dir:
            i = Signal(pin.width, name="{}_xdr_i".format(pin.name))
        if "o" in pin.dir:
            o = Signal(pin.width, name="{}_xdr_o".format(pin.name))
        if pin.dir in ("oe", "io"):
            t = Signal(pin.width, name="{}_xdr_t".format(pin.name))

        if pin.xdr == 0:
            if "i" in pin.dir:
                i = pin_i
            if "o" in pin.dir:
                o = pin_o
            if pin.dir in ("oe", "io"):
                t = Repl(~pin.oe, pin.width)
        elif pin.xdr == 1:
            if "i" in pin.dir:
                get_ireg(pin.i_clk, i, pin_i)
            if "o" in pin.dir:
                get_oreg(pin.o_clk, pin_o, o)
            if pin.dir in ("oe", "io"):
                get_oereg(pin.o_clk, ~pin.oe, t)
        elif pin.xdr == 2:
            if "i" in pin.dir:
                get_iddr(pin.i_clk, i, pin_i0, pin_i1)
            if "o" in pin.dir:
                get_oddr(pin.o_clk, pin_o0, pin_o1, o)
            if pin.dir in ("oe", "io"):
                get_oereg(pin.o_clk, ~pin.oe, t)
        elif pin.xdr == 4:
            if "i" in pin.dir:
                get_iddrx2(pin.i_clk, pin.i_fclk, i, pin_i0, pin_i1, pin_i2, pin_i3)
            if "o" in pin.dir:
                get_oddrx2(pin.o_clk, pin.o_fclk, pin_o0, pin_o1, pin_o2, pin_o3, o)
            if pin.dir in ("oe", "io"):
                get_oereg(pin.o_clk, ~pin.oe, t)
        elif pin.xdr == 7:
            if "i" in pin.dir:
                get_iddr71(pin.i_clk, pin.i_fclk, i, pin_i0, pin_i1, pin_i2, pin_i3, pin_i4, pin_i5, pin_i6)
            if "o" in pin.dir:
                get_oddr71(pin.o_clk, pin.o_fclk, pin_o0, pin_o1, pin_o2, pin_o3, pin_o4, pin_o5, pin_o6, o)
            if pin.dir in ("oe", "io"):
                get_oereg(pin.o_clk, ~pin.oe, t)
        elif pin.xdr == 8:
            if "i" in pin.dir:
                get_iddrx4(pin.i_clk, pin.i_fclk, i, pin_i0, pin_i1, pin_i2, pin_i3, pin_i4, pin_i5, pin_i6, pin_i7)
            if "o" in pin.dir:
                get_oddrx4(pin.o_clk, pin.o_fclk, pin_o0, pin_o1, pin_o2, pin_o3, pin_o4, pin_o5, pin_o6, pin_07, o)
            if pin.dir in ("oe", "io"):
                get_oereg(pin.o_clk, ~pin.oe, t)
        elif pin.xdr == 10:
            if "i" in pin.dir:
                get_iddrx5(pin.i_clk, pin.i_fclk, i, pin_i0, pin_i1, pin_i2, pin_i3, pin_i4, pin_i5, pin_i6, pin_i7, pin_i8, pin_i9)
            if "o" in pin.dir:
                get_oddrx5(pin.o_clk, pin.o_fclk, pin_o0, pin_o1, pin_o2, pin_o3, pin_o4, pin_o5, pin_o6, pin_07, pin_o8, pin_o9, o)
            if pin.dir in ("oe", "io"):
                get_oereg(pin.o_clk, ~pin.oe, t)
        else:
            assert False

        return (i, o, t)

    def get_input(self, pin, port, attrs, invert):
        self._check_feature(
            "single-ended input",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, i_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("IB",
                i_I=port.io[bit],
                o_O=i[bit]
            )
        return m

    def get_output(self, pin, port, attrs, invert):
        self._check_feature(
            "single-ended output",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("OB",
                i_I=o[bit],
                o_O=port.io[bit]
            )
        return m

    def get_tristate(self, pin, port, attrs, invert):
        self._check_feature(
            "single-ended tristate",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("OBZ",
                i_T=t[bit],
                i_I=o[bit],
                o_O=port.io[bit]
            )
        return m

    def get_input_output(self, pin, port, attrs, invert):
        self._check_feature(
            "single-ended input/output",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, i_invert=invert, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("BB",
                i_T=t[bit],
                i_I=o[bit],
                o_O=i[bit],
                io_B=port.io[bit]
            )
        return m

    def get_diff_input(self, pin, port, attrs, invert):
        self._check_feature(
            "differential input",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, i_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("IB",
                i_I=port.p[bit],
                o_O=i[bit]
            )
        return m

    def get_diff_output(self, pin, port, attrs, invert):
        self._check_feature(
            "differential output",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("OB",
                i_I=o[bit],
                o_O=port.p[bit],
            )
        return m

    def get_diff_tristate(self, pin, port, attrs, invert):
        self._check_feature(
            "differential tristate",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("OBZ",
                i_T=t[bit],
                i_I=o[bit],
                o_O=port.p[bit],
            )
        return m

    def get_diff_input_output(self, pin, port, attrs, invert):
        self._check_feature(
            "differential input/output",
            pin,
            attrs,
            valid_xdrs=(0, 1, 2, 4, 7, 8, 10),
            valid_attrs=True,
        )
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, i_invert=invert, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("BB",
                i_T=t[bit],
                i_I=o[bit],
                o_O=i[bit],
                io_B=port.p[bit],
            )
        return m

    # CDC primitives are not currently specialized for Nexus.
    # While Radiant supports false path constraints; nextpnr-nexus does not.

