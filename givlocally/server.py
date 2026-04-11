"""Flask web server for GivLocally."""

from __future__ import annotations

import logging
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, url_for

from .config import InverterConfig
from .reader import InverterReader
from .writer import InverterWriter

log = logging.getLogger(__name__)


def create_app(config: InverterConfig, inv_type: str = "", min_soc: int = 4) -> Flask:
    app = Flask(__name__)
    app.secret_key = "givlocally-local"

    def _reader() -> InverterReader:
        return InverterReader(config)

    def _writer() -> InverterWriter:
        return InverterWriter(config, inv_type=inv_type)

    def _ok(msg: str):
        flash(msg, "success")
        return redirect(url_for("index"))

    def _err(msg: str):
        flash(msg, "error")
        return redirect(url_for("index"))

    # ── Pages ─────────────────────────────────────────────────────────────────

    @app.route("/")
    def index():
        snap = None
        error = None
        try:
            snap = _reader().read_all()
        except Exception as exc:
            error = str(exc)
        return render_template("index.html", snap=snap, error=error,
                               now=datetime.now(), inv_type=inv_type)

    # ── Battery control ───────────────────────────────────────────────────────

    @app.route("/battery/charge", methods=["POST"])
    def battery_charge():
        try:
            _writer().force_charge()
            return _ok("Battery charging from mains at full power. "
                       "Use Normal mode to return to automatic control.")
        except Exception as exc:
            return _err(f"Force charge failed: {exc}")

    @app.route("/battery/export", methods=["POST"])
    def battery_export():
        try:
            _writer().force_export(min_soc=min_soc)
            return _ok("Battery discharging at full power — surplus exported to grid. "
                       "Use Normal mode to return to automatic control.")
        except Exception as exc:
            return _err(f"Force export failed: {exc}")

    @app.route("/battery/normal", methods=["POST"])
    def battery_normal():
        try:
            _writer().set_normal_mode(min_soc=min_soc)
            return _ok(f"Battery returned to normal automatic mode (SOC reserve: {min_soc}%).")
        except Exception as exc:
            return _err(f"Normal mode failed: {exc}")

    # ── Charge slots ──────────────────────────────────────────────────────────

    @app.route("/charge-slot/set", methods=["POST"])
    def charge_slot_set():
        try:
            slot = int(request.form["slot"])
            start = request.form["start"]
            end = request.form["end"]
            target_soc = int(request.form["target_soc"])
            _writer().set_charge_slot(slot, start, end, target_soc)
            return _ok(f"Charge slot {slot} set: {start} → {end} @ {target_soc}%.")
        except Exception as exc:
            return _err(f"Set charge slot failed: {exc}")

    @app.route("/charge-slot/clear", methods=["POST"])
    def charge_slot_clear():
        try:
            slot = int(request.form["slot"])
            _writer().clear_charge_slot(slot)
            return _ok(f"Charge slot {slot} cleared.")
        except Exception as exc:
            return _err(f"Clear charge slot failed: {exc}")

    # ── Discharge slots ───────────────────────────────────────────────────────

    @app.route("/discharge-slot/set", methods=["POST"])
    def discharge_slot_set():
        try:
            slot = int(request.form["slot"])
            start = request.form["start"]
            end = request.form["end"]
            floor_soc = int(request.form["floor_soc"])
            _writer().set_discharge_slot(slot, start, end, floor_soc)
            return _ok(f"Discharge slot {slot} set: {start} → {end}, floor {floor_soc}%.")
        except Exception as exc:
            return _err(f"Set discharge slot failed: {exc}")

    @app.route("/discharge-slot/clear", methods=["POST"])
    def discharge_slot_clear():
        try:
            slot = int(request.form["slot"])
            _writer().clear_discharge_slot(slot)
            return _ok(f"Discharge slot {slot} cleared.")
        except Exception as exc:
            return _err(f"Clear discharge slot failed: {exc}")

    # ── Export slots ──────────────────────────────────────────────────────────

    @app.route("/export-slot/set", methods=["POST"])
    def export_slot_set():
        try:
            slot = int(request.form["slot"])
            start = request.form["start"]
            end = request.form["end"]
            floor_soc = int(request.form["floor_soc"])
            _writer().set_export_slot(slot, start, end, floor_soc)
            return _ok(f"Export slot {slot} set: {start} → {end}, floor {floor_soc}%.")
        except Exception as exc:
            return _err(f"Set export slot failed: {exc}")

    @app.route("/export-slot/clear", methods=["POST"])
    def export_slot_clear():
        try:
            slot = int(request.form["slot"])
            _writer().clear_export_slot(slot)
            return _ok(f"Export slot {slot} cleared.")
        except Exception as exc:
            return _err(f"Clear export slot failed: {exc}")

    # ── Time sync ─────────────────────────────────────────────────────────────

    @app.route("/time-sync", methods=["POST"])
    def time_sync():
        try:
            now = datetime.now()
            _writer().sync_time(now)
            return _ok(f"Inverter clock set to {now.strftime('%Y-%m-%d %H:%M:%S')}.")
        except Exception as exc:
            return _err(f"Time sync failed: {exc}")

    return app
