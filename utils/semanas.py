"""
utils/semanas.py
Helpers para semanas ISO (YYYY-WNN).
Una semana ISO va de lunes a domingo.
Ejemplo: 2026-W13 = semana del 23 al 29 de marzo de 2026.
"""
from datetime import date, timedelta
from typing import Tuple


def get_semana_iso(fecha) -> str:
    """
    Devuelve la semana ISO de una fecha como string YYYY-WNN.
    Acepta date o datetime.
    Ejemplo: date(2026, 3, 25) → "2026-W13"
    """
    if hasattr(fecha, "date"):
        fecha = fecha.date()
    iso = fecha.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def get_rango_semana(semana_iso: str) -> Tuple[date, date]:
    """
    Devuelve (lunes, domingo) de una semana ISO.
    Ejemplo: "2026-W13" → (date(2026,3,23), date(2026,3,29))
    """
    year_str, week_str = semana_iso.split("-W")
    year, week = int(year_str), int(week_str)
    lunes = date.fromisocalendar(year, week, 1)
    domingo = lunes + timedelta(days=6)
    return lunes, domingo


def semanas_entre(fecha_inicio, fecha_fin) -> list[str]:
    """
    Devuelve lista de semanas ISO entre dos fechas (inclusive), en orden cronológico.
    Ejemplo: semanas_entre(date(2026,1,5), date(2026,1,18)) → ["2026-W02", "2026-W03"]
    """
    if hasattr(fecha_inicio, "date"):
        fecha_inicio = fecha_inicio.date()
    if hasattr(fecha_fin, "date"):
        fecha_fin = fecha_fin.date()

    semanas = []
    lunes_actual, _ = get_rango_semana(get_semana_iso(fecha_inicio))
    lunes_fin, _ = get_rango_semana(get_semana_iso(fecha_fin))

    while lunes_actual <= lunes_fin:
        semanas.append(get_semana_iso(lunes_actual))
        lunes_actual += timedelta(weeks=1)

    return semanas


def semana_anterior(semana_iso: str) -> str:
    """Devuelve la semana ISO anterior. Ejemplo: "2026-W13" → "2026-W12"."""
    lunes, _ = get_rango_semana(semana_iso)
    return get_semana_iso(lunes - timedelta(weeks=1))
