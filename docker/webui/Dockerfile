# The default base image is the one built from the repo's docker/Dockerfile, tagged fizgig:desktop.
# Override with --build-arg BASE_IMAGE=<name>.
# The pod template's public 8081 mapping must not be used with this image, and 8081 is not published.

ARG BASE_IMAGE=fizgig:desktop

FROM node:22-bookworm-slim AS webui
WORKDIR /src/webui
COPY webui/package.json webui/package-lock.json webui/tsconfig.json webui/vite.config.ts webui/index.html ./
COPY webui/src ./src
RUN npm ci
# The repo's npm run build also refreshes API types with the local venv. This stage
# typechecks the committed types and builds the page. Source is copied without node_modules.
RUN npx tsc --noEmit && npx vite build

FROM ${BASE_IMAGE}

COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscale /usr/local/bin/tailscale
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscaled /usr/local/bin/tailscaled

COPY requirements-web.txt /opt/fizgig/requirements-web.txt
COPY src/ /opt/fizgig/src/
COPY lora_trainer_gui.py /opt/fizgig/lora_trainer_gui.py
COPY --from=webui /src/webui/dist /opt/fizgig/webui/dist

RUN pip install -r /opt/fizgig/requirements-web.txt

ENV PYTHONPATH=/opt/fizgig/src
WORKDIR /opt/fizgig

COPY docker/webui/entrypoint.sh /usr/local/bin/fizgig-webui-entrypoint.sh
RUN chmod +x /usr/local/bin/fizgig-webui-entrypoint.sh

VOLUME /var/lib/tailscale

ENTRYPOINT ["/usr/local/bin/fizgig-webui-entrypoint.sh"]
