"""CLI entry point for GivLocally."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict

import click
from rich.console import Console

from .config import InverterConfig
from .display import print_snapshot
from .reader import InverterReader
from .writer import InverterWriter

err = Console(stderr=True)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """GivLocally — local control of GivEnergy inverters without the cloud."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command("read")
@click.option(
    "--host",
    default="192.168.0.100",
    show_default=True,
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=8899,
    show_default=True,
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--batteries",
    default=1,
    show_default=True,
    envvar="GIVENERGY_BATTERIES",
    help="Number of battery packs connected.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--output",
    type=click.Choice(["pretty", "json"], case_sensitive=False),
    default="pretty",
    show_default=True,
    help="Output format.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_read(
    host: str,
    port: int,
    batteries: int,
    retries: int,
    output: str,
    verbose: bool,
) -> None:
    """Read all settings and real-time data from the inverter."""

    _setup_logging(verbose)

    config = InverterConfig(
        host=host,
        port=port,
        number_batteries=batteries,
        retries=retries,
    )

    try:
        reader = InverterReader(config)
        snapshot = reader.read_all()
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    if output == "json":
        data = asdict(snapshot)
        # Convert datetime to ISO string for JSON serialisation
        if data.get("system_time") is not None:
            data["system_time"] = str(data["system_time"])
        click.echo(json.dumps(data, indent=2))
    else:
        print_snapshot(snapshot)


@cli.command("summary")
@click.option(
    "--host",
    default="192.168.0.100",
    show_default=True,
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=8899,
    show_default=True,
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_summary(host: str, port: int, retries: int, verbose: bool) -> None:
    """Print a one-line summary of current inverter state."""
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        snap = InverterReader(config).read_all()
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

    solar_kw = (snap.p_pv1_w + snap.p_pv2_w) / 1000
    load_kw = snap.p_load_w / 1000
    bat_kw = abs(snap.p_battery_w) / 1000
    grid_kw = abs(snap.p_grid_w) / 1000
    soc = snap.battery_soc_pct

    if snap.p_battery_w > 50:
        bat_status = f"[yellow]charging {bat_kw:.2f} kW[/yellow]"
    elif snap.p_battery_w < -50:
        bat_status = f"[cyan]discharging {bat_kw:.2f} kW[/cyan]"
    else:
        bat_status = "[dim]idle[/dim]"

    if snap.p_grid_w > 50:
        grid_status = f"exporting [green]{grid_kw:.2f} kW[/green]"
    elif snap.p_grid_w < -50:
        grid_status = f"importing [red]{grid_kw:.2f} kW[/red]"
    else:
        grid_status = "[dim]idle[/dim]"

    console = Console()
    console.print(
        f"Solar [green]{solar_kw:.2f} kW[/green]  "
        f"Load [red]{load_kw:.2f} kW[/red]  "
        f"Grid {grid_status}  "
        f"Battery {bat_status} @ [bold]{soc}%[/bold]"
    )


def _common_connection_options(fn):
    """Decorator that attaches the shared host/port/batteries/retries options."""
    fn = click.option(
        "--inv-type",
        default="",
        show_default=True,
        envvar="GIVENERGY_INV_TYPE",
        type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
        help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
    )(fn)
    fn = click.option(
        "--retries",
        default=3,
        show_default=True,
        help="Number of connection attempts before giving up.",
    )(fn)
    fn = click.option(
        "--port",
        default="192.168.0.100",
        show_default=True,
        envvar="GIVENERGY_PORT",
        help="Modbus TCP port on the inverter.",
    )(fn)
    fn = click.option(
        "--host",
        default="192.168.0.100",
        show_default=True,
        envvar="GIVENERGY_HOST",
        help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
    )(fn)
    return fn


@cli.group("charge-slot")
def charge_slot_group() -> None:
    """Manage timed charge slots on the inverter."""


@charge_slot_group.command("set")
@click.argument("slot", type=click.IntRange(1, 10))
@click.argument("start")
@click.argument("end")
@click.argument("target_soc", metavar="SOC", type=click.IntRange(4, 100))
@click.option(
    "--host",
    default="192.168.0.100",
    show_default=True,
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=8899,
    show_default=True,
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default="",
    show_default=True,
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_charge_slot_set(
    slot: int,
    start: str,
    end: str,
    target_soc: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Configure a timed charge slot.

    \b
    Arguments:
      SLOT   Slot number to configure (1–10).
      START  Time to start charging, in HH:MM format.
      END    Time to stop charging, in HH:MM format.
      SOC    Target state of charge in percent (4–100). The inverter stops
             charging early if the battery reaches this level before END.

    \b
    Examples:
      givlocally charge-slot set 1 01:00 05:00 100
          Slot 1: charge from 01:00 to 05:00, fill to 100%.
      givlocally charge-slot set 2 23:30 06:00 80
          Slot 2: charge from 23:30 to 06:00, stop at 80%.
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).set_charge_slot(slot, start, end, target_soc)
        err.print(f"[green]Charge slot {slot} set to {start} → {end} @ {target_soc}%[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@charge_slot_group.command("clear")
@click.argument("slot", type=click.IntRange(1, 10))
@click.option(
    "--host",
    default="192.168.0.100",
    show_default=True,
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=8899,
    show_default=True,
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default="",
    show_default=True,
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_charge_slot_clear(
    slot: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Disable charge SLOT by resetting its times to 00:00.

    SLOT is 1–10.

    Example: givlocally charge-slot clear 1
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).clear_charge_slot(slot)
        err.print(f"[green]Charge slot {slot} cleared[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@cli.group("discharge-slot")
def discharge_slot_group() -> None:
    """Manage timed discharge slots on the inverter."""


@discharge_slot_group.command("set")
@click.argument("slot", type=click.IntRange(1, 10))
@click.argument("start")
@click.argument("end")
@click.argument("floor_soc", metavar="SOC", type=click.IntRange(4, 100))
@click.option(
    "--host",
    default="192.168.0.100",
    show_default=True,
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=8899,
    show_default=True,
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default="",
    show_default=True,
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_discharge_slot_set(
    slot: int,
    start: str,
    end: str,
    floor_soc: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Configure a timed discharge slot.

    \b
    Arguments:
      SLOT   Slot number to configure (1–10).
      START  Time to start discharging, in HH:MM format.
      END    Time to stop discharging, in HH:MM format.
      SOC    Floor state of charge in percent (4–100). The inverter stops
             discharging early if the battery reaches this level before END.

    \b
    Examples:
      givlocally discharge-slot set 1 16:00 20:00 10
          Slot 1: discharge from 16:00 to 20:00, stop at 10%.
      givlocally discharge-slot set 2 07:00 09:00 20
          Slot 2: discharge from 07:00 to 09:00, stop at 20%.
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).set_discharge_slot(slot, start, end, floor_soc)
        err.print(f"[green]Discharge slot {slot} set to {start} → {end}, floor {floor_soc}%[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


@discharge_slot_group.command("clear")
@click.argument("slot", type=click.IntRange(1, 10))
@click.option(
    "--host",
    default="192.168.0.100",
    show_default=True,
    envvar="GIVENERGY_HOST",
    help="IP address (or hostname) of the GivEnergy inverter / WiFi dongle.",
)
@click.option(
    "--port",
    default=8899,
    show_default=True,
    envvar="GIVENERGY_PORT",
    help="Modbus TCP port on the inverter.",
)
@click.option(
    "--retries",
    default=3,
    show_default=True,
    help="Number of connection attempts before giving up.",
)
@click.option(
    "--inv-type",
    default="",
    show_default=True,
    envvar="GIVENERGY_INV_TYPE",
    type=click.Choice(["", "3ph", "ems"], case_sensitive=False),
    help="Inverter variant: blank = standard Gen3, '3ph' = three-phase, 'ems' = EMS.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cmd_discharge_slot_clear(
    slot: int,
    host: str,
    port: int,
    retries: int,
    inv_type: str,
    verbose: bool,
) -> None:
    """Disable discharge SLOT by resetting its times to 00:00.

    SLOT is 1–10.

    Example: givlocally discharge-slot clear 1
    """
    _setup_logging(verbose)
    config = InverterConfig(host=host, port=port, retries=retries)
    try:
        InverterWriter(config, inv_type=inv_type).clear_discharge_slot(slot)
        err.print(f"[green]Discharge slot {slot} cleared[/green]")
    except Exception as exc:
        err.print(f"[bold red]Error:[/bold red] {exc}")
        if verbose:
            import traceback
            traceback.print_exc()
        import sys
        sys.exit(1)


if __name__ == "__main__":
    cli()
