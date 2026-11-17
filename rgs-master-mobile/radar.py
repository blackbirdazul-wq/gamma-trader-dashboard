"""Coleta horária suplementar; reutiliza a metodologia do painel."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from app import BR, SYMS, GROUPS, get_one, get_di, fresh, group_summary, divergence

OUTPUT = Path(__file__).resolve().parent / "docs" / "radar.json"


def collect():
    with ThreadPoolExecutor(max_workers=3) as pool:
        di = pool.submit(get_di)
        rows = list(pool.map(get_one, SYMS))
        raw = {**{row["code"]: row for row in rows}, **di.result()}
    now = datetime.now(timezone.utc)
    quotes = {code: fresh(row, now) for code, row in raw.items()}
    summaries = {name: group_summary(codes, quotes) for name, codes in GROUPS.items()}
    # Não duplicar séries de candles em cada registro do histórico.
    slim = {code: {k: v for k, v in row.items() if k not in ("line", "times")}
            for code, row in quotes.items()}
    return dict(collected_at=now.isoformat(), summaries=summaries, quotes=slim,
                notes=divergence(summaries["GLOBAL"], summaries["BRASIL"], quotes))


def save_snapshot(snapshot, path=OUTPUT):
    records = []
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        records = old.get("history", [])
    records = [r for r in records if r["collected_at"] != snapshot["collected_at"]]
    records.append(snapshot)
    payload = dict(schema_version=1, latest=snapshot, history=records[-220:])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                               default=lambda v: v.isoformat(), indent=2), encoding="utf-8")
    os.replace(temp, path)


if __name__ == "__main__":
    save_snapshot(collect())
