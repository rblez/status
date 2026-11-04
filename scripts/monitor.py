#!/usr/bin/env python3
"""Tiendly status monitor: ping services and update static JSON data files.

Runs in GitHub Actions every 5 minutes (and can run locally).
Reads the existing status.json / incidents.json, appends the new check,
updates uptime, opens/closes incidents, and writes them back.
No database, no secrets — the files ARE the data.
"""
import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATUS_PATH = os.path.join(ROOT, "status.json")
INCIDENTS_PATH = os.path.join(ROOT, "incidents.json")

SERVICES = {
    "web": "https://www.tiendly.lat/",
    "app": "https://app.tiendly.lat/login",
    "api": "https://www.tiendly.lat/api/health",
}

# Human-readable names for incident descriptions.
SERVICE_LABELS = {"web": "La web", "app": "La app", "api": "La API"}

MAX_HISTORY = 90          # checks kept per service
MAX_INCIDENTS = 30        # days of checks used for uptime_30d
MAX_INCIDENTS_LIST = 50   # incidents kept
CHECK_INTERVAL_MIN = 5    # workflow cadence, used to estimate uptime window
SLOW_MS = 2000            # response above this = degraded performance


def is_up(v):
    """True si el chequeo cuenta como 'arriba' para uptime y barras.
    Acepta el formato nuevo (str: 'ok'/'slow'/'down') y el viejo (bool)."""
    if isinstance(v, bool):
        return v
    return v in ("ok", "slow")


def service_status(ok, ms):
    """Per-service level: ok | slow | down."""
    if not ok:
        return "down"
    if ms is not None and ms > SLOW_MS:
        return "slow"
    return "ok"


def overall_status(states):
    """Overall level: operational | degraded | partial | major."""
    downs = sum(1 for s in states if s == "down")
    slows = sum(1 for s in states if s == "slow")
    if downs == len(states) and states:
        return "major"
    if downs > 0:
        return "partial"
    if slows > 0:
        return "degraded"
    return "operational"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check(url, retries=2):
    """Ping a URL. Up = HTTP status < 400. Retries on failure."""
    for attempt in range(retries + 1):
        start = time.time()
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "TiendlyStatus/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                ms = int((time.time() - start) * 1000)
                return r.status < 400, ms
        except urllib.error.HTTPError as e:
            # An HTTP response (even 5xx) means the server answered.
            ms = int((time.time() - start) * 1000)
            return e.code < 400, ms
        except Exception:
            if attempt < retries:
                time.sleep(3)
                continue
            return False, None


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main():
    ts = now_iso()

    status = load_json(STATUS_PATH, {
        "checked_at": ts,
        "services": {},
        "history": {},
        "uptime_30d": {},
    })
    incidents = load_json(INCIDENTS_PATH, [])
    if not isinstance(incidents, list):
        incidents = []

    status.setdefault("services", {})
    status.setdefault("history", {})
    status.setdefault("uptime_30d", {})

    # How many checks cover ~30 days at the workflow cadence.
    window = int((30 * 24 * 60) / CHECK_INTERVAL_MIN)

    for svc, url in SERVICES.items():
        ok, ms = check(url)
        st = service_status(ok, ms)
        print(f"{svc}: {'OK' if ok else 'DOWN'} {ms}ms ({st})")

        prev = status["services"].get(svc, {})
        prev_ok = prev.get("ok")

        status["services"][svc] = {"ok": ok, "response_ms": ms, "status": st}

        hist = status["history"].get(svc, [])
        if not isinstance(hist, list):
            hist = []
        # Guardar el NIVEL ('ok'/'slow'/'down'), no solo un booleano:
        # un servicio lento antes quedaba como True y la barrita salía verde
        # aunque hubiera un incidente de rendimiento degradado.
        hist.append(st)
        status["history"][svc] = hist[-MAX_HISTORY:]

        # Uptime over the last 30 days of checks.
        # 'slow' sigue contando como arriba (responde, solo lento).
        recent = hist[-window:]
        if recent:
            up = sum(1 for v in recent if is_up(v))
            status["uptime_30d"][svc] = round(100.0 * up / len(recent), 2)
        else:
            status["uptime_30d"][svc] = 100.0

        # Incident logic: ok -> down opens one; down -> ok closes it.
        if prev_ok is True and not ok:
            label = SERVICE_LABELS.get(svc, svc)
            incidents.insert(0, {
                "service": svc,
                "started_at": ts,
                "ended_at": None,
                "duration_minutes": None,
                "description": f"{label} está caída.",
            })
            print(f"incident opened: {svc}")
        elif prev_ok is False and ok:
            for inc in incidents:
                if inc.get("service") == svc and not inc.get("ended_at"):
                    inc["ended_at"] = ts
                    start = datetime.strptime(
                        inc["started_at"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                    end = datetime.strptime(
                        ts, "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                    minutes = max(1, int((end - start).total_seconds() // 60))
                    inc["duration_minutes"] = minutes
                    label = SERVICE_LABELS.get(svc, svc)
                    inc["description"] = (
                        f"{label} estuvo caída {minutes} "
                        f"minuto{'s' if minutes != 1 else ''}."
                    )
                    print(f"incident closed: {svc} ({minutes} min)")
                    break

    incidents = incidents[:MAX_INCIDENTS_LIST]
    status["checked_at"] = ts
    status["overall"] = overall_status(
        [status["services"][s]["status"] for s in SERVICES]
    )

    save_json(STATUS_PATH, status)
    save_json(INCIDENTS_PATH, incidents)
    print(f"updated status.json at {ts}")


if __name__ == "__main__":
    main()
