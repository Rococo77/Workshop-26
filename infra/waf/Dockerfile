# WAF = nginx + ModSecurity + OWASP Core Rule Set (filtrage applicatif, sujet §3.4).
# Image CRS officielle ; en production, épingler une version précise (ex. 4.10.0).
FROM owasp/modsecurity-crs:nginx-alpine

# Moteur de règles actif (blocage réel, pas seulement détection).
ENV MODSEC_RULE_ENGINE=On \
    PARANOIA=1 \
    ANOMALY_INBOUND=5 \
    ANOMALY_OUTBOUND=4

# Routage inverse personnalisé (3 upstreams) + zones de rate limiting +
# include dynamique de la blocklist alimentée par le moteur de remédiation.
COPY default.conf.template /etc/nginx/templates/conf.d/default.conf.template

# Répertoire des règles dynamiques (blocklist). Monté en volume partagé ;
# le glob *.conf tolère l'absence de fichier au démarrage.
RUN mkdir -p /etc/nginx/dynamic

EXPOSE 8080
