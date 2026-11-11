"""RGS MASTER MOBILE — painel gratuito Streamlit + Yahoo Finance."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import math

import pandas as pd
import streamlit as st
import yfinance as yf

BR = ZoneInfo("America/Sao_Paulo")
SYMS = {
    "ES": ("ES=F", "S&P 500 futuro", 1, 0.15),
    "DXY": ("DX-Y.NYB", "Índice do dólar", -1, 0.10),
    "VIX": ("^VIX", "Volatilidade", -1, 1.00),
    "EWZ": ("EWZ", "ETF Brasil", 1, 0.40),
    "NQ": ("NQ=F", "Nasdaq futuro (reserva)", 1, 0.20),
}
st.set_page_config(page_title="RGS MASTER MOBILE", page_icon="📊", layout="centered")
st.markdown("""<style>
.block-container{padding-top:1.1rem}
h1{font-size:1.85rem!important}
div[data-testid="stMetric"]{padding:.7rem;border-radius:.7rem;border:1px solid #5b627030}
</style>""", unsafe_allow_html=True)

def good(x):
    try:
        n = float(x)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None

def get_one(code):
    ticker, name, direction, threshold = SYMS[code]
    result = dict(code=code, name=name, price=None, pct=None, time=None,
                  valid=False, reason="Indisponível", line=[])
    try:
        item = yf.Ticker(ticker)
        bars = item.history(period="5d", interval="5m", prepost=True,
                            auto_adjust=False, timeout=12)
        if bars is None or bars.empty or "Close" not in bars:
            return result
        bars = bars.dropna(subset=["Close"])
        if bars.empty:
            return result
        price = good(bars["Close"].iloc[-1])
        ts = pd.Timestamp(bars.index[-1]).to_pydatetime()
        if ts.tzinfo is None or price is None:
            result["reason"] = "Horário ou preço inválido"
            return result
        now = datetime.now(timezone.utc)
        stale = max(0, (now-ts.astimezone(timezone.utc)).total_seconds()/60)
        result.update(price=price, time=ts.astimezone(BR),
                      line=[float(v) for v in bars["Close"].tail(72).tolist()])
        previous = None
        try:
            previous = good(item.fast_info.get("previous_close"))
        except Exception:
            pass
        if previous is None:
            daily = item.history(period="10d", interval="1d", auto_adjust=False,
                                 timeout=12)
            if daily is not None and not daily.empty and "Close" in daily:
                candle_day = ts.date()
                earlier = daily[daily.index.date < candle_day]
                if not earlier.empty:
                    previous = good(earlier["Close"].iloc[-1])
        if previous:
            result["pct"] = (price/previous-1)*100
        if stale > 45:
            result["reason"] = f"Cotação antiga ({stale:.0f} min)"
        elif previous is None:
            result["reason"] = "Sem fechamento anterior"
        else:
            result["valid"] = True
            result["reason"] = "Cotação válida"
    except Exception as exc:
        result["reason"] = "Erro Yahoo: " + type(exc).__name__
    return result

@st.cache_data(ttl=80, show_spinner=False)
def fetch_all():
    with ThreadPoolExecutor(max_workers=3) as pool:
        values = list(pool.map(get_one, SYMS.keys()))
    return {v["code"]: v for v in values}

def state(code, row):
    if not row["valid"] or row["pct"] is None:
        return "SEM DADOS"
    pct = row["pct"]
    threshold = SYMS[code][3]
    if abs(pct) < threshold:
        return "NEUTRO"
    return "ON" if (1 if pct > 0 else -1) == SYMS[code][2] else "OFF"

st.caption("RGS • MONITOR GLOBAL · CELULAR")
st.title("📊 RGS MASTER MOBILE")
st.caption("Yahoo Finance · ES · DXY · VIX · EWZ")
with st.expander("⚙️ Configurações e metodologia"):
    use_nq = st.checkbox("Trocar VIX por Nasdaq futuro (NQ) quando VIX não estiver válido", value=True)
    st.info("As variações usam o fechamento anterior informado pelo Yahoo. "
            "Os filtros são heurísticos, sem validação por backtest. "
            "Cotação atrasada mais de 45 minutos não pontua.")
st.caption("Horários principais (Brasília): 08:50 · 09:00 · 09:25 · 10:00")

@st.fragment(run_every="90s")
def screen():
    now = datetime.now(timezone.utc).astimezone(BR)
    left, right = st.columns([2, 1])
    left.caption("Atualização: " + now.strftime("%d/%m/%Y %H:%M:%S"))
    if right.button("↻ Atualizar", use_container_width=True):
        fetch_all.clear()
    with st.spinner("Consultando Yahoo Finance…"):
        quotes = fetch_all()
    active = ["ES", "DXY", "VIX", "EWZ"]
    if use_nq and not quotes["VIX"]["valid"] and quotes["NQ"]["valid"]:
        active[2] = "NQ"
        st.warning("VIX sem cotação válida; Nasdaq futuro usado como substituto.")
    labels = {code: state(code, quotes[code]) for code in active}
    on = sum(v=="ON" for v in labels.values())
    off = sum(v=="OFF" for v in labels.values())
    valid = sum(v!="SEM DADOS" for v in labels.values())
    score = on-off
    classification = ("INCONCLUSIVO" if valid < 3 else
                      "RISK ON" if score >= 3 else
                      "RISK OFF" if score <= -3 else "MISTO / NEUTRO")
    color = "#2ecb93" if classification=="RISK ON" else "#ff7070" if classification=="RISK OFF" else "#e0bf66"
    st.markdown(f'<div style="border:1px solid #64748b50;padding:18px;border-radius:14px">'
                f'<small>LEITURA GLOBAL</small>'
                f'<h2 style="color:{color};margin:6px 0">{classification}</h2>'
                f'<strong>Score {score:+d}/4</strong> · {valid}/4 válidos '
                f'· {on} ON · {off} OFF</div>', unsafe_allow_html=True)
    if classification in ("RISK ON","RISK OFF"):
        st.caption("Viés contextual; confirmar preço, DI, WDO e fluxo antes de operar WIN.")
    else:
        st.caption("Sinais mistos ou insuficientes; não antecipar direção do WIN.")
    col = st.columns(2)
    for i, code in enumerate(active):
        r = quotes[code]
        with col[i%2]:
            price = f'{r["price"]:,.2f}' if r["price"] is not None else "—"
            delta = f'{r["pct"]:+.2f}%' if r["pct"] is not None else None
            st.metric(f'{code} · {labels[code]}', price, delta, delta_color="off")
            st.caption(r["name"] + " · " + r["reason"])
            if r["time"]:
                st.caption("Candle " + r["time"].strftime("%H:%M %d/%m") + " BRT")
    st.caption("DXY e VIX em queda contam como RISK ON. EWZ pode ficar sem dados antes da sessão americana.")
    with st.expander("📈 Gráficos de 5 minutos"):
        for code in active:
            if quotes[code]["line"]:
                st.write("**" + code + "**")
                st.line_chart(pd.DataFrame({"Preço": quotes[code]["line"]}), height=150)
            else:
                st.caption(f"{code}: sem histórico")
    st.divider()
    st.caption("Yahoo Finance pode limitar ou atrasar dados. "
               "Painel informativo: não emite ordens, alertas em segundo plano ou sinais de entrada.")
screen()
