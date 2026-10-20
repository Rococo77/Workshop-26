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

# Répertoire des règles dynamiques (blocklist), dans /etc/nginx possédé par nginx.
RUN mkdir -p /etc/nginx/dynamic

# Répertoire de logs dédié : /var/log appartient à root -> on le crée en root
# puis on revient à l'utilisateur nginx de l'image (moindre privilège préservé).
# Le volume nommé hérite de ces permissions (1777) à sa première initialisation.
USER root
# Correctifs de sécurité des paquets Alpine de l'image CRS (ex. libx11 signalé
# par Trivy) : l'image amont n'est pas reconstruite à chaque CVE.
RUN apk upgrade --no-cache
# Journal pré-créé en 0666 : l'exporter (autre uid) doit pouvoir le tronquer.
RUN mkdir -p /var/log/ra && chmod 1777 /var/log/ra \
    && touch /var/log/ra/ra_access.log && chmod 0666 /var/log/ra/ra_access.log
USER nginx

EXPOSE 8080
