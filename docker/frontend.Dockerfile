# Frontend : fichiers statiques servis par nginx, qui relaie /api vers le backend.
# Contexte de build : la racine du dépôt. C'est ce conteneur seul qui peut être placé en DMZ.
FROM nginx:1.27-alpine

# Adresse du backend (zone interne), remplacée dans la configuration au démarrage.
ENV BACKEND_URL=http://backend:8110

COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY docker/proxy_params_conges /etc/nginx/proxy_params_conges
COPY static /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1/healthz || exit 1
