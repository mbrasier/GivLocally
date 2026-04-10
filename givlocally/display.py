"""Rich-formatted display of inverter snapshots."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from .reader import BatterySnapshot, InverterSnapshot, TimeSlot

console = Console()


def _kw(watts: float) -> str:
    return f"{watts / 1000:.2f} kW"


def _slot_str(slot: TimeSlot) -> str:
    if not slot.is_active:
        return "[dim]disabled[/dim]"
    return f"{slot.start} → {slot.end}"


def _section(title: str) -> Table:
    t = Table(
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 1),
        title=f"[bold cyan]{title}[/bold cyan]",
        title_justify="left",
    )
    t.add_column("Field", style="dim", min_width=34)
    t.add_column("Value", style="bold white")
    return t


def print_snapshot(snap: InverterSnapshot) -> None:
    """Render the full inverter snapshot to stdout using Rich."""

    title = f"[bold green]GivLocally — {snap.serial_number or 'GivEnergy Inverter'}[/bold green]"
    console.print(Panel(title, expand=False))

    # ── Device identity ──────────────────────────────────────────────────────
    t = _section("Device Identity")
    t.add_row("Serial number", snap.serial_number or "[dim]unknown[/dim]")
    t.add_row("Model", snap.model or "[dim]unknown[/dim]")
    t.add_row("Firmware", snap.firmware_version or "[dim]n/a[/dim]")
    t.add_row("DSP firmware", snap.dsp_firmware_version or "[dim]n/a[/dim]")
    t.add_row("ARM firmware", snap.arm_firmware_version or "[dim]n/a[/dim]")
    t.add_row("Batteries detected", str(snap.num_batteries))
    if snap.system_time:
        t.add_row("Inverter date/time", snap.system_time.strftime("%Y-%m-%d %H:%M:%S"))
    console.print(t)

    # ── Real-time power ───────────────────────────────────────────────────────
    t = _section("Real-time Power")
    pv_total = snap.p_pv1_w + snap.p_pv2_w
    t.add_row("PV total", _kw(pv_total))
    t.add_row("  PV1", _kw(snap.p_pv1_w))
    t.add_row("  PV2", _kw(snap.p_pv2_w))
    bat_label = "Charging" if snap.p_battery_w >= 0 else "Discharging"
    t.add_row(f"Battery ({bat_label})", _kw(abs(snap.p_battery_w)))
    grid_label = "Export" if snap.p_grid_w >= 0 else "Import"
    t.add_row(f"Grid ({grid_label})", _kw(abs(snap.p_grid_w)))
    t.add_row("Load demand", _kw(snap.p_load_w))
    if snap.p_inverter_out_w:
        t.add_row("Inverter output", _kw(snap.p_inverter_out_w))
    if snap.p_eps_backup_w:
        t.add_row("EPS backup", _kw(snap.p_eps_backup_w))
    console.print(t)

    # ── Electrical readings ───────────────────────────────────────────────────
    t = _section("Electrical Readings")
    t.add_row("AC voltage", f"{snap.v_ac1:.1f} V")
    t.add_row("AC current", f"{snap.i_ac1:.2f} A")
    t.add_row("AC frequency", f"{snap.f_ac1:.2f} Hz")
    t.add_row("PV1 voltage / current", f"{snap.v_pv1:.1f} V  /  {snap.i_pv1:.2f} A")
    t.add_row("PV2 voltage / current", f"{snap.v_pv2:.1f} V  /  {snap.i_pv2:.2f} A")
    t.add_row("Battery voltage / current", f"{snap.v_battery:.2f} V  /  {snap.i_battery:.2f} A")
    if snap.v_p_bus or snap.v_n_bus:
        t.add_row("DC bus P/N", f"{snap.v_p_bus:.1f} V  /  {snap.v_n_bus:.1f} V")
    console.print(t)

    # ── Temperatures ──────────────────────────────────────────────────────────
    t = _section("Temperatures")
    t.add_row("Inverter heatsink", f"{snap.temp_inverter_c:.1f} °C")
    t.add_row("Charger", f"{snap.temp_charger_c:.1f} °C")
    t.add_row("Battery (inverter-side)", f"{snap.temp_battery_c:.1f} °C")
    console.print(t)

    # ── Battery settings ──────────────────────────────────────────────────────
    t = _section("Battery Settings")
    t.add_row("State of charge", f"[green]{snap.battery_soc_pct}%[/green]")
    t.add_row(
        "Charging",
        "[green]Enabled[/green]" if snap.charge_enabled else "[red]Disabled[/red]",
    )
    t.add_row(
        "Discharging",
        "[green]Enabled[/green]" if snap.discharge_enabled else "[red]Disabled[/red]",
    )
    t.add_row("Charge target SOC", f"{snap.charge_target_soc}%")
    t.add_row("Eco mode", "[green]On[/green]" if snap.eco_mode else "Off")
    t.add_row("UPS mode", "[green]On[/green]" if snap.enable_ups_mode else "Off")
    if snap.battery_pause_mode:
        t.add_row("Battery pause mode", snap.battery_pause_mode)
    if snap.pv_power_setting:
        t.add_row("PV power setting", str(snap.pv_power_setting))
    console.print(t)

    # ── Charge / discharge schedule ───────────────────────────────────────────
    t = _section("Charge / Discharge Schedule")
    active_charge = [s for s in snap.charge_slots if s.is_active]
    active_discharge = [s for s in snap.discharge_slots if s.is_active]

    if active_charge:
        for slot in active_charge:
            t.add_row(
                f"Charge slot {slot.index}",
                f"{_slot_str(slot)}  [dim](target {snap.charge_target_socs[slot.index - 1]}%)[/dim]",
            )
    else:
        t.add_row("Charge slots", "[dim]none active[/dim]")

    if active_discharge:
        for slot in active_discharge:
            t.add_row(
                f"Discharge slot {slot.index}",
                f"{_slot_str(slot)}  [dim](target {snap.discharge_target_socs[slot.index - 1]}%)[/dim]",
            )
    else:
        t.add_row("Discharge slots", "[dim]none active[/dim]")
    console.print(t)

    # ── Energy — today ────────────────────────────────────────────────────────
    t = _section("Energy Today")
    t.add_row("PV1 generation", f"{snap.e_pv1_day_kwh:.2f} kWh")
    t.add_row("PV2 generation", f"{snap.e_pv2_day_kwh:.2f} kWh")
    t.add_row("Grid import", f"{snap.e_grid_in_day_kwh:.2f} kWh")
    t.add_row("Grid export", f"{snap.e_grid_out_day_kwh:.2f} kWh")
    t.add_row("Battery charged", f"{snap.e_battery_charge_today_kwh:.2f} kWh")
    t.add_row("Battery discharged", f"{snap.e_battery_discharge_today_kwh:.2f} kWh")
    console.print(t)

    # ── Energy — lifetime ─────────────────────────────────────────────────────
    t = _section("Lifetime Energy Totals")
    t.add_row("PV generation", f"{snap.e_pv_total_kwh:.1f} kWh")
    t.add_row("Battery charged", f"{snap.e_battery_charge_total_kwh:.1f} kWh")
    t.add_row("Battery discharged", f"{snap.e_battery_discharge_total_kwh:.1f} kWh")
    t.add_row("Inverter export", f"{snap.e_inverter_export_total_kwh:.1f} kWh")
    console.print(t)

    # ── Battery packs ─────────────────────────────────────────────────────────
    for bat in snap.batteries:
        _print_battery(bat)


def _print_battery(bat: BatterySnapshot) -> None:
    t = _section(f"Battery Pack {bat.index}")
    t.add_row("Serial number", bat.serial_number or "[dim]unknown[/dim]")
    t.add_row("BMS firmware", bat.bms_firmware or "[dim]n/a[/dim]")
    t.add_row("State of charge", f"[green]{bat.state_of_charge}%[/green]")
    t.add_row("Design capacity", f"{bat.cap_design_ah:.1f} Ah")
    t.add_row("Calibrated capacity", f"{bat.cap_calibrated_ah:.1f} Ah")
    t.add_row("Remaining capacity", f"{bat.cap_remaining_ah:.1f} Ah")
    t.add_row("Cycle count", str(bat.num_cycles))
    t.add_row("Cell count", str(bat.num_cells))
    t.add_row("Temp (max)", f"{bat.temp_max_c:.1f} °C")
    t.add_row("Temp (min)", f"{bat.temp_min_c:.1f} °C")
    t.add_row("Temp (MOS)", f"{bat.temp_mos_c:.1f} °C")
    t.add_row("Output voltage", f"{bat.v_out:.2f} V")
    t.add_row("Energy charged (total)", f"{bat.e_charge_total_kwh:.1f} kWh")
    t.add_row("Energy discharged (total)", f"{bat.e_discharge_total_kwh:.1f} kWh")

    if bat.cell_voltages_mv:
        for chunk_start in range(0, len(bat.cell_voltages_mv), 4):
            chunk = bat.cell_voltages_mv[chunk_start : chunk_start + 4]
            cells = [f"C{chunk_start + j + 1:02d}:{v:.0f}mV" for j, v in enumerate(chunk)]
            label = f"Cell voltages {chunk_start + 1}–{chunk_start + len(chunk)}"
            t.add_row(label, "  ".join(cells))

    console.print(t)
