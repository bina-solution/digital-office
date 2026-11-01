FROM ghcr.io/openhands/agent-server:1.27.0-python
# Provider API keys — propagated by entrypoint wrapper
ENV OPENAI_API_KEY="" 
ENV DEEPSEEK_API_KEY=""
ENV GEMINI_API_KEY=""
ENV OH_ENABLE_VNC=true
ENV NOVNC_PORT=8011
COPY --chmod=755 entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh
ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
