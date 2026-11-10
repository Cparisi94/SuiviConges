# Frontend : fichiers statiques servis par nginx, qui relaie /api vers le backend.
# Contexte de build : frontend/. Deux variantes de configuration nginx :
#   nginx.conf.template      frontend du réseau interne (port 8111)
#   nginx.dmz.conf.template  frontend de la DMZ (port 8112) : routes réservées à l'interne bloquées
FROM nginx:1.27-alpine

ARG NGINX_TEMPLATE=nginx.conf.template

# Adresse du backend (zone interne), remplacée dans la configuration au démarrage.
ENV BACKEND_URL=http://backend:8110

COPY ${NGINX_TEMPLATE} /etc/nginx/templates/default.conf.template
COPY proxy_params_conges /etc/nginx/proxy_params_conges
COPY public /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1
