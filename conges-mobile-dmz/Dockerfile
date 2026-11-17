# Suivi des congés — version mobile (DMZ) : page autonome, aucune dépendance sur le reste du dépôt.
# Contexte de construction : ce dossier seul   ->   docker compose build (context: .)
FROM nginx:1.27-alpine
# Les modèles sont rendus au démarrage avec BACKEND_HOST / BACKEND_PORT (image officielle : /etc/nginx/templates)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY conges_mobile_proxy.inc.template /etc/nginx/templates/conges_mobile_proxy.inc.template
COPY public /usr/share/nginx/html
ENV BACKEND_HOST=backend BACKEND_PORT=8110
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1/healthz >/dev/null || exit 1
