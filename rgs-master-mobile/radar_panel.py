"""Exibe leituras históricas separadas do score atual."""
import json
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

BR = ZoneInfo("America/Sao_Paulo")
DATA = Path(__file__).resolve().parent / "docs" / "radar.json"


def snapshot_age(snapshot, now):
    stamp = datetime.fromisoformat(snapshot["collected_at"])
    if stamp.tzinfo is None:
        raise ValueError("Registro sem fuso")
    return (now - stamp).total_seconds() / 60, stamp.astimezone(BR)


def render_radar(current):
    st.subheader("🕘 Radar horário • informação suplementar")
    st.caption("Leituras automáticas previstas de segunda a sexta, 08h–18h BRT. "
               "Horários sujeitos a atraso. Não altera o score atual; não mede o WIN diretamente.")
    try:
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        if payload["schema_version"] != 1:
            raise ValueError("Formato incompatível")
        snapshot = payload["latest"]
        age, stamp = snapshot_age(snapshot, datetime.now(timezone.utc))
        if age < -5:
            raise ValueError("Registro futuro")
        summaries = snapshot["summaries"]
        st.caption("Última coleta: " + stamp.strftime("%d/%m/%Y %H:%M:%S") + f" BRT · há {max(0, age):.0f} min")
        if age > 90 or stamp.date() != datetime.now(BR).date():
            st.warning("RADAR ANTIGO — apenas histórico. Consulte as cotações atuais acima.")
        st.write("**Na coleta:** " + " · ".join(f"{name}: {summaries[name]['label']}" for name in ("GLOBAL", "BRASIL", "JUROS")))
        st.caption("Validade e direção abaixo são as observadas na coleta, não uma cotação em tempo real.")
        for note in snapshot.get("notes", []):
            st.write(note)
        for name in ("GLOBAL", "BRASIL"):
            before, after = summaries[name]["label"], current[name]["label"]
            st.write(f"{name}: radar {before} → painel agora {after}")
        with st.expander("Ativos e qualidade na coleta"):
            rows = []
            for code, row in snapshot["quotes"].items():
                rows.append({"Ativo": code, "Preço/taxa": row.get("price"),
                             "Variação %": row.get("pct"), "DI pb": row.get("bp"),
                             "Candle BRT": row.get("time"), "Qualidade na coleta": row.get("reason")})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption("DI sem horário verificável permanece fora do score. Coletas em feriados podem "
                       "conter mercados externos ativos; o radar não certifica que a B3 está aberta.")
        with st.expander("Histórico automático • últimas 220 leituras"):
            records = []
            for record in payload["history"]:
                _, ts = snapshot_age(record, datetime.now(timezone.utc))
                records.append({"Coleta BRT": ts.strftime("%Y-%m-%d %H:%M:%S"),
                                **{name: record["summaries"][name]["label"] for name in ("GLOBAL", "BRASIL", "JUROS")}})
            frame = pd.DataFrame(records)
            st.dataframe(frame, hide_index=True, use_container_width=True)
            st.download_button("Baixar radar CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                               "rgs_radar_horario.csv", "text/csv", key="radar_csv")
    except FileNotFoundError:
        st.info("Aguardando a primeira coleta automática do radar.")
    except (ValueError, KeyError, TypeError, OSError):
        st.warning("Radar indisponível ou arquivo inválido. O painel atual continua independente.")
