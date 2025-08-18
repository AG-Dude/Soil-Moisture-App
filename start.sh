#!/usr/bin/env bash
export STREAMLIT_SERVER_PORT=${PORT:-8501}
streamlit run app.py --server.port=$STREAMLIT_SERVER_PORT --server.enableCORS=true --server.enableXsrfProtection=false
