"""RGS MASTER MOBILE V2: contexto, qualidade e evolução, sem ordens."""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
import math
import json
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st
import yfinance as yf

BR = ZoneInfo("America/Sao_Paulo")
SYMS = {
    "ES": ("ES=F", "S&P 500 futuro", 1, 0.15),
    "DXY": ("DX-Y.NYB", "Índice do dólar", -1, 0.10),
    "VIX": ("^VIX", "Volatilidade", -1, 1.00),
    "EWZ": ("EWZ", "ETF Brasil", 1, 0.40),
    "VALE": ("VALE", "Vale ADR", 1, 0.40),
    "PBR": ("PBR", "Petrobras ADR", 1, 0.40),
    "NQ": ("NQ=F", "Nasdaq futuro • confirmação adicional", 1, 0.20),
}
DI_CODES = ("DI1F27", "DI1F29", "DI1F31", "DI1F33")
DI_URL = "https://cotacao.b3.com.br/mds/api/v1/DerivativeQuotation/DI1"
GROUPS = {"GLOBAL": ("ES", "DXY", "VIX"), "BRASIL": ("EWZ", "VALE", "PBR"), "JUROS": DI_CODES}
MAX_AGE = 45


def good(x):
    try:
        n = float(x)
        return n if math.isfinite(n) and n > 0 else None
    except (ValueError, TypeError):
        return None


def recent_move(series):
    """15 min entre candles próximos, sem atravessar noite ou lacuna grande."""
    if len(series) < 3:
        return None
    end = series.index[-1]
    earlier = series[series.index <= end - pd.Timedelta(minutes=15)]
    if earlier.empty:
        return None
    start = earlier.index[-1]
    window = series.loc[start:end]
    minutes = (end - start).total_seconds() / 60
    gaps = window.index.to_series().diff().dropna().dt.total_seconds()
    if start.date() != end.date() or not 15 <= minutes <= 20 or (gaps > 600).any():
        return None
    base = good(earlier.iloc[-1])
    return (float(series.iloc[-1]) / base - 1) * 100 if base else None


def get_one(code):
    ticker, name, _, _ = SYMS[code]
    result = dict(code=code, name=name, price=None, pct=None, time=None,
                  age=None, move=None, valid=False, reason="SEM DADOS", line=[], times=[], reference=None)
    try:
        item = yf.Ticker(ticker)
        bars = item.history(period="5d", interval="5m", prepost=True,
                            auto_adjust=False, timeout=12)
        if bars is None or bars.empty or "Close" not in bars:
            return result
        close = bars["Close"].dropna().sort_index()
        close = close[~close.index.duplicated(keep="last")]
        close = close[close.map(good).notna()]
        if close.empty:
            return result
        ts = pd.Timestamp(close.index[-1]).to_pydatetime()
        if ts.tzinfo is None:
            result["reason"] = "HORÁRIO INVÁLIDO"
            return result
        now = datetime.now(timezone.utc)
        age = (now - ts.astimezone(timezone.utc)).total_seconds() / 60
        price = float(close.iloc[-1])
        result.update(price=price, time=ts.astimezone(BR), age=max(0, age),
                      move=recent_move(close), line=close.tail(72).tolist(),
                      times=[t.to_pydatetime().astimezone(BR) for t in close.tail(72).index])
        if age < -5:
            result["reason"] = "HORÁRIO FUTURO — fora do score"
            return result
        # Uma única referência explícita: último candle diário anterior à data
        # local da cotação. Não misturar previous_close estendido com regular.
        daily = item.history(period="1mo", interval="1d", auto_adjust=False, timeout=12)
        previous = None
        if daily is not None and not daily.empty and "Close" in daily:
            earlier = daily[daily.index.date < ts.date()]["Close"].dropna().sort_index()
            if not earlier.empty:
                previous = good(earlier.iloc[-1])
                result["reference"] = str(earlier.index[-1].date())
        if previous is not None:
            result["pct"] = (price / previous - 1) * 100
        if age > MAX_AGE:
            result["reason"] = "COTAÇÃO ANTIGA — fora do score"
        elif previous is None:
            result["reason"] = "SEM REFERÊNCIA — fora do score"
        else:
            result["valid"] = True
            result["reason"] = "Cotação válida pelo limite de 45 min"
    except Exception as exc:
        result["reason"] = "FALHA YAHOO — " + type(exc).__name__
    return result


def parse_di(payload):
    """B3 rates are annual percent; Msg.dtTm is NOT a trade timestamp.

    This public snapshot has no per-instrument trade date/time. Fail closed:
    display genuine rates, never turn response freshness into quote freshness.
    """
    rows = {code: dict(code=code, name="DI janeiro/20" + code[-2:],
                      price=None, pct=None, bp=None, adjustment=None,
                      time=None, age=None, move=None, valid=False,
                      reason="SEM DADOS B3 — fora do score", line=[], times=[],
                      reference=None, snapshot=None) for code in DI_CODES}
    if not isinstance(payload, dict) or payload.get("BizSts", {}).get("cd") != "OK":
        return rows
    instruments = payload.get("Scty", [])
    if not isinstance(instruments, list):
        return rows
    for item in instruments:
        if not isinstance(item, dict) or item.get("symb") not in rows:
            continue
        row = rows[item["symb"]]
        q = item.get("SctyQtn") or {}
        rate = good(q.get("curPrc"))
        adjustment = good(q.get("prvsDayAdjstmntPric"))
        # Reject PU-like values: DI endpoint must return annual interest rates.
        if rate is None or rate >= 100 or adjustment is None or adjustment >= 100:
            continue
        row.update(price=rate, adjustment=adjustment,
                   pct=(rate / adjustment - 1) * 100,
                   bp=round((rate - adjustment) * 100, 6),
                   snapshot=payload.get("Msg", {}).get("dtTm"),
                   reason="SEM HORÁRIO DO NEGÓCIO — fora do score")
    return rows


def get_di():
    try:
        request = Request(DI_URL, headers={"Accept": "application/json"})
        with urlopen(request, timeout=12) as response:
            return parse_di(json.load(response))
    except Exception:
        rows = parse_di({})
        for row in rows.values():
            row["reason"] = "FALHA B3 — fora do score"
        return rows


def di_vote(bp):
    """One basis point threshold; lower rates favor ON in this heuristic."""
    if bp is None or not math.isfinite(bp):
        return "FORA DO SCORE"
    return "ON" if bp <= -1 else "OFF" if bp >= 1 else "NEUTRO"


def di_card(code, row):
    st.metric(code + " · " + state(code, row),
              f'{row["price"]:.3f}% a.a.' if row["price"] is not None else "—",
              f'{row["bp"]:+.2f} pb vs. ajuste anterior' if row["bp"] is not None else None,
              delta_color="off")
    st.caption(row["reason"])
    if row["adjustment"] is not None:
        st.caption(f'Ajuste anterior informado pela B3: {row["adjustment"]:.3f}% a.a.')
    if row["snapshot"]:
        st.caption("Horário da resposta B3 (não do negócio): " + str(row["snapshot"]))


@st.cache_data(ttl=80, show_spinner=False)
def fetch_all():
    with ThreadPoolExecutor(max_workers=3) as pool:
        di_future = pool.submit(get_di)
        values = list(pool.map(get_one, SYMS))
        di_rows = di_future.result()
    return {**{v["code"]: v for v in values}, **di_rows}


def fresh(row, now):
    """Reavaliar a idade mesmo quando a resposta veio do cache."""
    row = dict(row)
    if row["time"] is not None:
        age = (now - row["time"]).total_seconds() / 60
        row["age"] = max(0, age)
        if age > MAX_AGE:
            row.update(valid=False, reason="COTAÇÃO ANTIGA — fora do score")
    return row


def state(code, row):
    if not row["valid"] or row["pct"] is None:
        return "FORA DO SCORE"
    if code in DI_CODES:
        return di_vote(row.get("bp"))
    signed = row["pct"] * SYMS[code][2]
    if abs(signed) < SYMS[code][3]:
        return "NEUTRO"
    return "ON" if signed > 0 else "OFF"


def group_summary(codes, quotes):
    labels = [state(code, quotes[code]) for code in codes]
    valid = sum(x != "FORA DO SCORE" for x in labels)
    score = labels.count("ON") - labels.count("OFF")
    # Nenhum bloco recebe direção se faltar uma de suas três fontes.
    required_score = 3 if len(codes) == 4 else 2
    label = ("INCONCLUSIVO" if valid < len(codes) else
             "RISK ON" if score >= required_score else "RISK OFF" if score <= -required_score else "MISTO / NEUTRO")
    return dict(label=label, score=score, valid=valid)


def momentum_text(code, row):
    if not row["valid"] or row["move"] is None:
        return "Movimento recente indisponível"
    change = row["move"] * SYMS[code][2]
    threshold = SYMS[code][3] / 3
    if abs(change) < threshold:
        return "Contexto estável nos últimos ~15 min"
    return "Melhorando para risco nos últimos ~15 min" if change > 0 else "Piorando para risco nos últimos ~15 min"


def confirmation(previous, summary, times, now):
    """Só confirmar com novos candles de TODAS as fontes, não novo clique."""
    label = summary["label"]
    current = dict(label=label, times=times, at=now, confirmed=False)
    if label not in ("RISK ON", "RISK OFF"):
        return current, "Sem direção confirmada"
    if previous and previous["label"] == label:
        elapsed = (now - previous["at"]).total_seconds()
        if 0 <= elapsed <= 1200:
            progressed = all(t and p and t > p for t, p in zip(times, previous["times"]))
            if elapsed >= 60 and progressed:
                current["confirmed"] = True
                return current, "Confirmado em 2 leituras com novos candles"
            # Manter a primeira observação enquanto não chegam todos os candles.
            return previous, ("Confirmado em 2 leituras com novos candles" if previous["confirmed"]
                              else "Sinal inicial • aguardando novos candles")
    return current, "Sinal inicial • aguardando novos candles"


def divergence(global_s, brazil_s, quotes):
    g, b = global_s["label"], brazil_s["label"]
    messages = []
    if "INCONCLUSIVO" in (g, b):
        messages.append("Dados insuficientes para comparar Global e Brasil com direção completa.")
    elif g == b and g in ("RISK ON", "RISK OFF"):
        messages.append("Global e Brasil alinhados nesta leitura.")
    elif g in ("RISK ON", "RISK OFF"):
        messages.append("Divergência: Brasil não acompanha a direção global.")
    else:
        messages.append("Global misto: ainda não há alinhamento direcional entre os blocos.")
    es, nq = state("ES", quotes["ES"]), state("NQ", quotes["NQ"])
    if {es, nq} == {"ON", "OFF"}:
        messages.append("ES e NQ em direções opostas; bolsas americanas sem confirmação conjunta.")
    if {state("VALE", quotes["VALE"]), state("PBR", quotes["PBR"])} == {"ON", "OFF"}:
        messages.append("Vale e Petrobras divergem entre si.")
    return messages


def quote_card(code, row):
    if code in DI_CODES:
        di_card(code, row)
        return
    label = state(code, row)
    st.metric(f"{code} · {label}", f'{row["price"]:,.2f}' if row["price"] is not None else "—",
              f'{row["pct"]:+.2f}%' if row["pct"] is not None else None, delta_color="off")
    st.caption(row["name"] + " · " + row["reason"])
    if row["time"]:
        st.caption("Candle " + row["time"].strftime("%d/%m %H:%M") + f' BRT · idade {row["age"]:.0f} min')
    if row["reference"]:
        st.caption("Variação vs. fechamento diário Yahoo de " + row["reference"])
    st.caption(momentum_text(code, row))
    if row["valid"] and row["move"] is not None:
        st.caption(f'Movimento do preço em ~15 min: {row["move"]:+.2f}%')


def history_panel(quotes, summaries, now):
    day = now.date().isoformat()
    if st.session_state.get("history_day") != day:
        st.session_state["history_day"] = day
        st.session_state["readings"] = []
        st.session_state["slots"] = []
    st.subheader("Comparação da manhã")
    st.caption("Horários de Brasília: 08:50 · 09:25 · 09:50. Registra somente com esta página aberta; "
               "não recupera horários perdidos. Histórico desta sessão, que pode ser perdido ao fechar/recarregar. Exporte para guardar.")
    manual = st.button("Registrar leitura agora")
    minute = now.hour * 60 + now.minute
    target = next((label for label, m in [("08:50", 530), ("09:25", 565), ("09:50", 590)]
                   if m <= minute < m + 5 and label not in st.session_state["slots"]), None)
    if manual or target:
        record = {"Registro BRT": now.strftime("%Y-%m-%d %H:%M:%S"), "Janela": target or "Manual"}
        for name, summary in summaries.items():
            record[name] = summary["label"]
            record[name + " score"] = summary["score"]
        for code, row in quotes.items():
            record[code + " %"] = round(row["pct"], 3) if row["valid"] and row["pct"] is not None else None
            record[code + " candle BRT"] = row["time"].isoformat() if row["time"] else ""
            if code in DI_CODES:
                record[code + " pb"] = row.get("bp")
                record[code + " taxa informativa"] = row.get("price")
                record[code + " resposta B3"] = row.get("snapshot")
            record[code + " status"] = row["reason"]
        st.session_state["readings"] = (st.session_state["readings"] + [record])[-100:]
        if target:
            st.session_state["slots"] = st.session_state["slots"] + [target]
        st.success("Leitura registrada com o horário real da coleta.")
    readings = st.session_state["readings"]
    if readings:
        frame = pd.DataFrame(readings)
        st.dataframe(frame[["Registro BRT", "Janela", "GLOBAL", "GLOBAL score", "BRASIL", "BRASIL score"]],
                     hide_index=True, use_container_width=True)
        if len(readings) >= 2:
            first, last = readings[0], readings[-1]
            comparison = []
            for code in SYMS:
                a, b = first.get(code + " %"), last.get(code + " %")
                comparison.append({"Ativo": code, "Mudança desde a 1ª leitura (p.p.)":
                                   round(b - a, 3) if a is not None and b is not None else None})
            st.dataframe(pd.DataFrame(comparison), hide_index=True, use_container_width=True)
            st.caption("Mudança na variação diária em pontos percentuais; dados inválidos ficam em branco.")
        st.download_button("Baixar histórico CSV", frame.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"rgs_leituras_{day}.csv", mime="text/csv")
    else:
        st.info("Nenhuma leitura registrada nesta sessão.")


def main():
    st.set_page_config(page_title="RGS MASTER MOBILE", page_icon="📊", layout="centered")
    st.markdown("""<style>
    .block-container{padding-top:2.5rem;padding-bottom:2rem}
    h1{font-size:1.85rem!important}
    div[data-testid="stMetric"]{padding:.7rem;border-radius:.7rem;border:1px solid #5b627030}
    </style>""", unsafe_allow_html=True)
    st.caption("RGS • MONITOR GLOBAL · CELULAR · V3 • DI")
    st.title("📊 RGS MASTER MOBILE")
    st.caption("Global + Brasil + Juros DI • força recente • qualidade dos dados")
    with st.expander("⚙️ Metodologia e limites"):
        st.write("Global: ES, DXY e VIX. Brasil: EWZ, VALE e PBR. Cada bloco tem três votos iguais; "
                 "exige 3/3 válidos e saldo de pelo menos +2 ou −2 para indicar direção. "
                 "NQ é confirmação adicional, não substitui VIX e não soma voto.")
        st.write("DXY e VIX caindo favorecem ON na regra heurística. Limiares diários: ES 0,15%; "
                 "DXY 0,10%; VIX 1%; EWZ/VALE/PBR 0,40%; NQ 0,20%. Sem calibração por backtest.")
        st.write("Cotação com mais de 45 minutos fica fora do score, mesmo com preço disponível. "
                 "Válido não significa tempo real. Mercado fechado ou sem negócios pode produzir cotação antiga.")
        st.write("Variação contra o último candle diário Yahoo anterior à data da cotação. "
                 "Movimento recente usa ~15 minutos sem lacunas maiores que 10 minutos. "
                 "Confirmação exige a mesma direção com novos candles das três fontes, "
                 "entre 1 e 20 minutos da observação anterior; cliques repetidos não confirmam.")
        st.caption("EWZ e ADRs não representam todo o mercado brasileiro. Dados do Yahoo podem atrasar ou falhar.")
        st.write("Juros: DI1F27, DI1F29, DI1F31 e DI1F33. Queda da taxa favorece ON; alta favorece OFF. "
                 "Limiar de 1 ponto-base (0,01 ponto percentual); bloco exige 4/4 válidos e saldo de 3 votos. "
                 "Variação em pb contra a taxa de ajuste anterior fornecida pela B3, não contra o PU.")
        st.write("A fonte pública B3 consultada não fornece horário do negócio por contrato. "
                 "As taxas são informativas e permanecem FORA DO SCORE até haver uma fonte com horário verificável. "
                 "O horário da resposta não comprova atualização da cotação. Não usar CDI/Selic como substituto.")
    screen()


@st.fragment(run_every="90s")
def screen():
    if st.button("↻ Atualizar", use_container_width=True):
        fetch_all.clear()
    with st.spinner("Consultando Yahoo Finance e B3…"):
        raw = fetch_all()
    now = datetime.now(timezone.utc).astimezone(BR)
    quotes = {code: fresh(row, now) for code, row in raw.items()}
    st.caption("Consulta: " + now.strftime("%d/%m/%Y %H:%M:%S") + " BRT · atualiza a cada 90 s com a página aberta")
    core = [c for codes in GROUPS.values() for c in codes]
    count = sum(quotes[c]["valid"] for c in core)
    st.caption(f"QUALIDADE DOS DADOS · {count}/{len(core)} válidos para os blocos · NQ adicional: "
               + ("válido" if quotes["NQ"]["valid"] else "indisponível para confirmação"))
    summaries = {name: group_summary(codes, quotes) for name, codes in GROUPS.items()}
    for name, codes in GROUPS.items():
        summary = summaries[name]
        key = "confirmation_" + name
        previous = st.session_state.get(key)
        record, status = confirmation(previous, summary, [quotes[c]["time"] for c in codes], now)
        st.session_state[key] = record
        color = "#21966b" if summary["label"] == "RISK ON" else "#e04c58" if summary["label"] == "RISK OFF" else "#a77b12"
        st.markdown(f'<div style="border:1px solid #64748b50;padding:18px;border-radius:14px;margin-bottom:12px">'
                    f'<strong>{name}</strong><h2 style="color:{color};margin:6px 0">{summary["label"]}</h2>'
                    f'<strong>Score {summary["score"]:+d}/{len(codes)}</strong> · {summary["valid"]}/{len(codes)} válidos<br>{status}</div>',
                    unsafe_allow_html=True)
        moves = [quotes[c]["move"] * SYMS[c][2] / (SYMS[c][3] / 3)
                 for c in codes if c in SYMS and quotes[c]["valid"] and quotes[c]["move"] is not None]
        recent = sum(1 if v >= 1 else -1 if v <= -1 else 0 for v in moves)
        wording = ("Dados recentes insuficientes" if len(moves) < len(codes) else
                   "Melhorando para risco" if recent >= 2 else "Piorando para risco" if recent <= -2 else "Estável / misto")
        st.caption(f"{name} · Movimento recente: {wording} · {len(moves)}/{len(codes)} com janela de ~15 min")
    if summaries["JUROS"]["label"] == "INCONCLUSIVO":
        st.warning("DI: taxas reais disponíveis quando a B3 responde, mas sem horário do negócio verificável. "
                   "Juros fora do score; Global e Brasil continuam com suas próprias fontes. "
                   "O alinhamento completo com juros ainda não está confirmado.")
    st.subheader("Alinhamento e divergências")
    for message in divergence(summaries["GLOBAL"], summaries["BRASIL"], quotes):
        st.info(message)
    st.caption("Contexto do mercado, não sinal de entrada no WIN. Confirmação temporal não é probabilidade de acerto.")
    for name, codes in GROUPS.items():
        st.subheader({"GLOBAL": "🌐 Global", "BRASIL": "🇧🇷 Brasil nos EUA", "JUROS": "📉 Juros futuros DI • B3"}[name])
        for code in codes:
            quote_card(code, quotes[code])
    with st.expander("NQ • confirmação adicional, sem voto"):
        quote_card("NQ", quotes["NQ"])
    with st.expander("📈 Gráficos de 5 minutos"):
        for code, row in quotes.items():
            if row["line"]:
                st.write("**" + code + "**")
                st.line_chart(pd.DataFrame({"Preço": row["line"]}, index=pd.DatetimeIndex(row["times"])), height=150)
                st.caption("Últimos candles disponíveis; consulte a data e a validade acima.")
    with st.expander("🕘 Leituras 08:50 · 09:25 · 09:50 e histórico"):
        history_panel(quotes, summaries, now)
    st.divider()
    st.caption("V3 · Yahoo Finance + B3 (DI informativo) · Sem ordens ou notificações em segundo plano. "
               "Registros e confirmações pertencem apenas a esta sessão; não há coleta agendada com o aplicativo fechado.")


if __name__ == "__main__":
    main()
