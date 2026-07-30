FROM ghcr.io/home-assistant/base:3.23

ARG BUILD_VERSION
ARG BUILD_ARCH

RUN apk add --no-cache python3 py3-websocket-client

COPY app /opt/ha-ai-maintainer
COPY rootfs /

RUN chmod a+x /etc/services.d/ha-ai-maintainer/run

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.title="Home Assistant App: HA AI Maintainer" \
    org.opencontainers.image.description="Read-only local Home Assistant health observer" \
    org.opencontainers.image.source="https://github.com/Mqbretrofit/ha-ai-maintainer"
