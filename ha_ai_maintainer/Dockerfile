FROM ghcr.io/home-assistant/base:3.23

ARG BUILD_VERSION
ARG BUILD_ARCH

RUN apk add --no-cache git nodejs npm python3 py3-websocket-client \
    && npm install --global @openai/codex@0.146.0 \
    && codex --version \
    && npm cache clean --force

COPY app /opt/ha-ai-maintainer
COPY rootfs /

RUN chmod a+x /etc/services.d/ha-ai-maintainer/run

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Home Assistant App: HA AI Maintainer" \
    org.opencontainers.image.description="Approval-gated Home Assistant diagnostics and local Codex repairs" \
    org.opencontainers.image.source="https://github.com/Mqbretrofit/ha-ai-maintainer"
