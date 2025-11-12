import streamlit as st
import yfinance as yf
import pandas as pd
import time
from datetime import datetime, timedelta
import warnings
import numpy as np
from scipy.stats import norm

warnings.filterwarnings("ignore")

# ========== CONFIGURAÇÃO DA PÁGINA ==========
st.set_page_config(
    page_title="Dashboard EWZ + S&P500 + Nasdaq com Greeks",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ========== CSS PERSONALIZADO ==========
st.markdown("""
<style>
    .main-header {
        font-size: 2.8rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 1rem;
    }
    .ewz-card {
        background: linear-gradient(135deg, #2ecc71, #27ae60);
        color: white;
        padding: 20px;
        border-radius: 15px;
        margin: 10px 0;
        border: 3px solid #27ae60;
    }
    .sp500-card {
        background: linear-gradient(135deg, #00cc96, #00a085);
        color: white;
        padding: 20px;
        border-radius: 15px;
        margin: 10px 0;
        border: 3px solid #00a085;
    }
    .nasdaq-card {
        background: linear-gradient(135deg, #636efa, #4a54e1);
        color: white;
        padding: 20px;
        border-radius: 15px;
        margin: 10px 0;
        border: 3px solid #4a54e1;
    }
    .fibonacci-level {
        padding: 6px 10px;
        margin: 3px 0;
        border-radius: 5px;
        font-weight: bold;
        text-align: center;
        font-size: 0.9rem;
    }
    .fib-236 { background-color: #ff6b6b; color: white; }
    .fib-382 { background-color: #ffa726; color: white; }
    .fib-500 { background-color: #ffee58; color: black; }
    .fib-618 { background-color: #66bb6a; color: white; }
    .fib-786 { background-color: #42a5f5; color: white; }
    .fib-current { 
        border: 3px solid #000000 !important;
        box-shadow: 0 0 10px rgba(0,0,0,0.5);
    }
    .volume-high { color: #00cc96; font-weight: bold; }
    .volume-low { color: #ef553b; font-weight: bold; }
    .metric-card {
        background: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
        margin: 5px 0;
    }
    .delta-positive { color: #00cc96; font-weight: bold; }
    .delta-negative { color: #ef553b; font-weight: bold; }
    .gamma-high { color: #ff6b6b; font-weight: bold; }
    .greeks-card {
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        padding: 15px;
        border-radius: 10px;
        margin: 5px 0;
    }
</style>
""", unsafe_allow_html=True)

# ========== CONFIGURAÇÕES ==========
TICKERS = {
    "EWZ Brasil": {"symbol": "EWZ", "color": "#2ecc71", "card_class": "ewz-card"},
    "S&P 500": {"symbol": "SPY", "color": "#00CC96", "card_class": "sp500-card"},
    "Nasdaq": {"symbol": "QQQ", "color": "#636EFA", "card_class": "nasdaq-card"}
}

# ========== FUNÇÕES GREGOS (DELTA & GAMMA) ==========
def calculate_black_scholes_greeks(S, K, T, r, sigma, option_type='call'):
    """
    Calcula Delta e Gamma usando Black-Scholes
    S: Preço atual do ativo
    K: Strike price (usaremos preços próximos)
    T: Tempo até expiração (em anos)
    r: Taxa livre de risco
    sigma: Volatilidade
    """
    try:
        if T <= 0:
            return 0.5, 0
        
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        
        if option_type == 'call':
            delta = norm.cdf(d1)
        else:
            delta = norm.cdf(d1) - 1
        
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        
        return round(delta, 4), round(gamma, 4)
    
    except:
        return 0.5, 0

def calculate_implied_volatility(hist_data):
    """Calcula volatilidade implícita baseada no histórico"""
    if len(hist_data) < 2:
        return 0.2
    
    returns = np.log(hist_data['Close'] / hist_data['Close'].shift(1))
    volatility = returns.std() * np.sqrt(252)
    
    return max(0.1, min(0.8, volatility))

def calculate_delta_gamma_analysis(current_price, hist_data):
    """Análise completa de Delta e Gamma"""
    sigma = calculate_implied_volatility(hist_data)
    
    r = 0.05
    T = 30/365
    
    strikes = [
        current_price * 0.95,
        current_price,
        current_price * 1.05
    ]
    
    deltas = []
    gammas = []
    
    for K in strikes:
        delta_call, gamma_call = calculate_black_scholes_greeks(
            current_price, K, T, r, sigma, 'call'
        )
        deltas.append(delta_call)
        gammas.append(gamma_call)
    
    avg_delta = np.mean(deltas)
    avg_gamma = np.mean(gammas)
    
    if avg_delta > 0.6:
        delta_signal = "📈 DELTA ALTO (Tendência Forte de Alta)"
        delta_class = "delta-positive"
    elif avg_delta < 0.4:
        delta_signal = "📉 DELTA BAIXO (Tendência Forte de Baixa)"
        delta_class = "delta-negative"
    else:
        delta_signal = "⚖️ DELTA NEUTRO (Mercado Equilibrado)"
        delta_class = ""
    
    if avg_gamma > 0.1:
        gamma_signal = "🎯 GAMMA ALTO (Alta Sensibilidade)"
        gamma_class = "gamma-high"
    else:
        gamma_signal = "📊 GAMMA BAIXO (Baixa Sensibilidade)"
        gamma_class = ""
    
    return {
        'delta': avg_delta,
        'gamma': avg_gamma,
        'delta_signal': delta_signal,
        'gamma_signal': gamma_signal,
        'delta_class': delta_class,
        'gamma_class': gamma_class,
        'volatility': sigma
    }

# ========== FUNÇÕES AVANÇADAS ==========
def get_advanced_data(ticker, period="2d"):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval="15m")
        
        if not hist.empty and len(hist) > 1:
            current_price = hist['Close'].iloc[-1]
            previous_price = hist['Close'].iloc[-2]
            change_percent = ((current_price - previous_price) / previous_price) * 100
            
            high_2d = hist['High'].max()
            low_2d = hist['Low'].min()
            volume_current = hist['Volume'].iloc[-1] if 'Volume' in hist.columns else 0
            volume_avg = hist['Volume'].mean() if 'Volume' in hist.columns else 0
            
            fibonacci_levels = calculate_fibonacci_2d(hist)
            rsi = calculate_rsi(hist['Close'])
            
            mm_9 = hist['Close'].tail(9).mean() if len(hist) >= 9 else current_price
            mm_21 = hist['Close'].tail(21).mean() if len(hist) >= 21 else current_price
            mm_50 = hist['Close'].tail(50).mean() if len(hist) >= 50 else current_price
            
            greeks_data = calculate_delta_gamma_analysis(current_price, hist)
            
            fib_signal = get_fibonacci_signal(current_price, fibonacci_levels)
            mm_signal = get_moving_average_signal(current_price, mm_9, mm_21, mm_50)
            volume_signal = get_volume_signal(volume_current, volume_avg)
            
            return {
                'current_price': round(current_price, 2),
                'change_percent': round(change_percent, 2),
                'high_2d': round(high_2d, 2),
                'low_2d': round(low_2d, 2),
                'volume_current': volume_current,
                'volume_avg': volume_avg,
                'volume_signal': volume_signal,
                'rsi': rsi,
                'mm_9': round(mm_9, 2),
                'mm_21': round(mm_21, 2),
                'mm_50': round(mm_50, 2),
                'mm_signal': mm_signal,
                'fibonacci': fibonacci_levels,
                'fib_signal': fib_signal,
                'delta': greeks_data['delta'],
                'gamma': greeks_data['gamma'],
                'delta_signal': greeks_data['delta_signal'],
                'gamma_signal': greeks_data['gamma_signal'],
                'delta_class': greeks_data['delta_class'],
                'gamma_class': greeks_data['gamma_class'],
                'volatility': greeks_data['volatility'],
                'history': hist
            }
    except Exception as e:
        return None
    return None

def calculate_fibonacci_2d(hist_data):
    if len(hist_data) < 10:
        return {}
    
    high_2d = hist_data['High'].max()
    low_2d = hist_data['Low'].min()
    diff = high_2d - low_2d
    
    fibonacci_levels = {
        '0.0': round(high_2d, 2),
        '0.236': round(high_2d - (0.236 * diff), 2),
        '0.382': round(high_2d - (0.382 * diff), 2),
        '0.500': round(high_2d - (0.500 * diff), 2),
        '0.618': round(high_2d - (0.618 * diff), 2),
        '0.786': round(high_2d - (0.786 * diff), 2),
        '1.0': round(low_2d, 2),
    }
    
    return fibonacci_levels

def calculate_rsi(prices, period=14):
    if len(prices) < period:
        return 50
    
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi.iloc[-1], 2) if not pd.isna(rsi.iloc[-1]) else 50

def get_fibonacci_signal(current_price, fibonacci_levels):
    if not fibonacci_levels:
        return "NEUTRO"
    
    fib_236 = fibonacci_levels.get('0.236', 0)
    fib_382 = fibonacci_levels.get('0.382', 0)
    fib_500 = fibonacci_levels.get('0.500', 0)
    fib_618 = fibonacci_levels.get('0.618', 0)
    
    if current_price >= fib_236:
        return "🔴 RESISTÊNCIA FORTE"
    elif current_price >= fib_382:
        return "🟠 RESISTÊNCIA MÉDIA"
    elif current_price >= fib_500:
        return "🟡 ZONA NEUTRA"
    elif current_price >= fib_618:
        return "🟢 SUPORTE MÉDIO"
    else:
        return "🔵 SUPORTE FORTE"

def get_moving_average_signal(current_price, mm_9, mm_21, mm_50):
    if mm_9 > mm_21 and mm_21 > mm_50 and current_price > mm_9:
        return "🟢 COMPRA FORTE"
    elif mm_9 > mm_21 and current_price > mm_9:
        return "🟢 COMPRA"
    elif mm_9 < mm_21 and mm_21 < mm_50 and current_price < mm_9:
        return "🔴 VENDA FORTE"
    elif mm_9 < mm_21 and current_price < mm_9:
        return "🔴 VENDA"
    else:
        return "⚪ NEUTRO"

def get_volume_signal(current_volume, avg_volume):
    if avg_volume == 0:
        return "NORMAL"
    
    ratio = current_volume / avg_volume
    if ratio > 2.0:
        return "📈 VOLUME MUITO ALTO"
    elif ratio > 1.5:
        return "📈 VOLUME ALTO"
    elif ratio < 0.5:
        return "📉 VOLUME BAIXO"
    else:
        return "📊 VOLUME NORMAL"

def get_current_fib_level(current_price, fibonacci_levels):
    if not fibonacci_levels:
        return "0.0"
    
    levels = [
        ('0.0', fibonacci_levels['0.0']),
        ('0.236', fibonacci_levels['0.236']),
        ('0.382', fibonacci_levels['0.382']),
        ('0.500', fibonacci_levels['0.500']),
        ('0.618', fibonacci_levels['0.618']),
        ('0.786', fibonacci_levels['0.786']),
        ('1.0', fibonacci_levels['1.0'])
    ]
    
    for i in range(len(levels) - 1):
        current_level, current_value = levels[i]
        next_level, next_value = levels[i + 1]
        
        if current_value >= current_price >= next_value:
            return current_level
    
    return "1.0"

# ========== SIDEBAR ==========
with st.sidebar:
    st.title("⚙️ Controles do Dashboard")
    auto_refresh = st.checkbox("Atualização Automática", value=True)
    refresh_interval = st.slider("Intervalo (segundos)", 10, 120, 30)
    
    st.subheader("📊 Alertas")
    alert_fibonacci = st.checkbox("Alertas Fibonacci", value=True)
    alert_volume = st.checkbox("Alertas Volume", value=True)
    alert_greeks = st.checkbox("Alertas Delta/Gamma", value=True)

# ========== HEADER ==========
st.markdown('<h1 class="main-header">🎯 DASHBOARD EWZ + S&P500 + NASDAQ COM GREGOS</h1>', unsafe_allow_html=True)
st.markdown("---")

# ========== BUSCAR DADOS ==========
all_data = {}

for name, config in TICKERS.items():
    data = get_advanced_data(config["symbol"])
    if data:
        all_data[name] = {
            "config": config,
            "data": data
        }

# ========== CARDS PRINCIPAIS ==========
for name, item in all_data.items():
    config = item["config"]
    data = item["data"]
    
    with st.container():
        st.markdown(f"""
        <div class='{config["card_class"]}'>
            <h2>📈 {name}</h2>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <div>
                    <h3 style='margin: 0; font-size: 2rem;'>${data['current_price']}</h3>
                    <p style='margin: 5px 0; font-size: 1.2rem;'>{data['change_percent']:+.2f}%</p>
                </div>
                <div style='text-align: right;'>
                    <p style='margin: 2px 0;'><strong>RSI:</strong> {data['rsi']:.1f}</p>
                    <p style='margin: 2px 0;'><strong>Fibonacci:</strong> {data['fib_signal']}</p>
                    <p style='margin: 2px 0;'><strong>Médias:</strong> {data['mm_signal']}</p>
                    <p style='margin: 2px 0;'><strong>Volume:</strong> {data['volume_signal']}</p>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown("#### 📊 Fibonacci 2 Dias")
            current_fib_level = get_current_fib_level(data['current_price'], data['fibonacci'])
            
            fib_levels = [
                ('0.0', '🎯 Topo', 'fib-236'),
                ('0.236', '23.6%', 'fib-236'),
                ('0.382', '38.2%', 'fib-382'),
                ('0.500', '50.0%', 'fib-500'),
                ('0.618', '61.8%', 'fib-618'),
                ('0.786', '78.6%', 'fib-786'),
                ('1.0', '🎯 Base', 'fib-236')
            ]
            
            for level_key, level_name, css_class in fib_levels:
                fib_value = data['fibonacci'].get(level_key, 0)
                is_current = (level_key == current_fib_level)
                
                extra_class = " fib-current" if is_current else ""
                display_text = f"<div class='fibonacci-level {css_class}{extra_class}'>{level_name}<br>${fib_value}</div>"
                
                if is_current:
                    display_text = f"<div class='fibonacci-level {css_class}{extra_class}'>🎯 {level_name}<br>${fib_value}</div>"
                
                st.markdown(display_text, unsafe_allow_html=True)
        
        with col2:
            st.markdown("#### 📈 Médias Móveis")
            
            st.markdown(f"""
            <div class='metric-card'>
                <strong>MM9 (Rápida):</strong> ${data['mm_9']}<br>
                <strong>MM21 (Média):</strong> ${data['mm_21']}<br>
                <strong>MM50 (Lenta):</strong> ${data['mm_50']}
            </div>
            """, unsafe_allow_html=True)
            
            if data['mm_9'] > data['mm_21'] and data['mm_21'] > data['mm_50']:
                st.success("✅ Tendência de ALTA")
            elif data['mm_9'] < data['mm_21'] and data['mm_21'] < data['mm_50']:
                st.error("❌ Tendência de BAIXA")
            else:
                st.warning("⚠️ Tendência NEUTRA")
        
        with col3:
            st.markdown("#### 📊 Volume & RSI")
            
            volume_ratio = data['volume_current'] / data['volume_avg'] if data['volume_avg'] > 0 else 1
            volume_class = "volume-high" if volume_ratio > 1.5 else "volume-low" if volume_ratio < 0.7 else ""
            
            st.markdown(f"""
            <div class='metric-card'>
                <strong>Volume Atual:</strong> <span class='{volume_class}'>{data['volume_current']:,.0f}</span><br>
                <strong>Volume Médio:</strong> {data['volume_avg']:,.0f}<br>
                <strong>Ratio Volume:</strong> <span class='{volume_class}'>{volume_ratio:.2f}x</span>
            </div>
            """, unsafe_allow_html=True)
            
            rsi_value = data['rsi']
            if rsi_value > 70:
                st.error(f"❌ RSI SOBREVENDIDO: {rsi_value:.1f}")
            elif rsi_value < 30:
                st.success(f"✅ RSI SOBRECOMPRADO: {rsi_value:.1f}")
            else:
                st.info(f"⚪ RSI NEUTRO: {rsi_value:.1f}")
        
        with col4:
            st.markdown("#### 🎯 Delta & Gamma")
            
            st.markdown(f"""
            <div class='greeks-card'>
                <strong>DELTA:</strong> <span class='{data['delta_class']}'>{data['delta']:.4f}</span><br>
                <strong>GAMMA:</strong> <span class='{data['gamma_class']}'>{data['gamma']:.4f}</span><br>
                <strong>VOLATILIDADE:</strong> {data['volatility']:.1%}
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"**{data['delta_signal']}**")
            st.markdown(f"**{data['gamma_signal']}**")
        
        st.markdown("---")

# ========== RESUMO GERAL ==========
if all_data:
    st.markdown("## 📈 RESUMO GERAL DO MERCADO")
    
    summary_cols = st.columns(4)
    
    buy_signals = sum(1 for item in all_data.values() if "COMPRA" in item['data']['mm_signal'])
    fib_support = sum(1 for item in all_data.values() if "SUPORTE" in item['data']['fib_signal'])
    high_delta = sum(1 for item in all_data.values() if item['data']['delta'] > 0.6)
    total_assets = len(all_data)
    
    with summary_cols[0]:
        st.metric("🟢 Sinais Compra", buy_signals)
    with summary_cols[1]:
        st.metric("📊 Fibonacci Suporte", fib_support)
    with summary_cols[2]:
        st.metric("🎯 Delta Alto", high_delta)
    with summary_cols[3]:
        st.metric("🔢 Total Ativos", total_assets)

# ========== FOOTER ==========
st.markdown("---")
st.markdown(f"**🕒 Atualizado:** {datetime.now().strftime('%H:%M:%S')}")

if auto_refresh:
    progress_bar = st.progress(0)
    for i in range(refresh_interval):
        progress_bar.progress((i + 1) / refresh_interval)
        time.sleep(1)
    st.rerun()
else:
    if st.button("🔄 Atualizar Dados", type="primary", use_container_width=True):
        st.rerun()


st.caption("🎯 **Dashboard Especial EWZ + S&P500 + Nasdaq - Análise Técnica Completa com Gregos**")
