# RGS MASTER MOBILE — Yahoo Finance / Python

Aplicação Streamlit para celular: Risk ON/OFF com ES, DXY, VIX e EWZ; NQ como substituto do VIX quando necessário.

### Streamlit Community Cloud
- Repositório: \`blackbirdazul-wq/gamma-trader-dashboard\`
- Branch: \`rgs-master-mobile-v1\`
- Arquivo: \`rgs-master-mobile/app.py\`
- Dependências: \`rgs-master-mobile/requirements.txt\`

Após autenticar em https://share.streamlit.io, clique em **Create app**, selecione os três campos acima e **Deploy**. O Streamlit pode solicitar autorização do GitHub.

A atualização ocorre a cada 90 segundos enquanto a página permanece aberta. Cotações antigas, indisponíveis ou sem fechamento anterior não contam no score. Os limites e sinais são heurísticos e não foram validados por backtest. Não executar ordens com base só no painel.
