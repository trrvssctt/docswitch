# Déploiement sur le VPS (185.215.165.43)

L'API tourne dans Docker, uniquement sur `127.0.0.1:8000`. Nginx est devant et fait le HTTPS
sur le port dédié **8445** (le 443 est déjà utilisé par les autres sites du VPS).
Les fichiers temporaires vivent en RAM (`tmpfs`) et sont supprimés à la fin de chaque requête.

**HTTPS sans nom de domaine.** Le serveur n'a qu'une adresse IP, donc on utilise un certificat
auto-signé valable 10 ans. L'app Android embarque ce certificat et ne fait confiance qu'à lui pour
cette IP : c'est aussi sûr qu'un certificat Let's Encrypt (et même plus strict). Si tu prends un
nom de domaine plus tard, voir « Passer à un nom de domaine » en bas.

Toutes les commandes ci-dessous sont à taper **sur le VPS**, sauf indication contraire.

---

## 1. Préparer le serveur (une seule fois)

Docker et Nginx sont déjà installés sur ce VPS (il héberge d'autres applis : on n'y touche pas).
DocSwitch utilise **uniquement** le port interne `127.0.0.1:8000` et le port public **8445**,
tous deux libres.

```bash
ssh root@185.215.165.43
docker --version && nginx -v
ss -tlnp | grep -E ':8000|:8445'   # ne doit rien afficher

# Si le pare-feu est actif, ouvrir le port 8445 :
ufw status
ufw allow 8445/tcp                 # seulement si « Status: active »
```

## 2. Envoyer le code (depuis le PC)

Seuls `backend/` et `deploy/` sont nécessaires sur le serveur. **Sur le PC**, à la racine du dépôt :

```bash
ssh root@185.215.165.43 "mkdir -p /opt/docswitch"
rsync -av --exclude '__pycache__' --exclude '.venv' --exclude '.pytest_cache' --exclude '.env' \
  backend deploy root@185.215.165.43:/opt/docswitch/
```

(`--exclude '.env'` évite d'écraser la clé du serveur lors des mises à jour.)

## 3. Créer la clé d'API

```bash
cd /opt/docswitch/deploy
cp .env.example .env
sed -i "s/^DOCSWITCH_API_KEY=.*/DOCSWITCH_API_KEY=$(openssl rand -hex 32)/" .env
chmod 600 .env
cat .env   # note la clé : elle va dans mobile/src/config/secrets.ts
```

## 4. Lancer l'API

```bash
cd /opt/docswitch/deploy
docker compose up -d --build        # ~3 min la première fois (LibreOffice)
docker compose ps
curl http://127.0.0.1:8000/health   # {"status":"ok","version":"1.0.0"}
```

## 5. Certificat HTTPS auto-signé

```bash
mkdir -p /etc/nginx/docswitch && cd /etc/nginx/docswitch
openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
  -keyout server.key -out server.crt \
  -subj "/CN=DocSwitch" \
  -addext "subjectAltName=IP:185.215.165.43" \
  -addext "basicConstraints=critical,CA:TRUE"
chmod 600 server.key
```

⚠️ **Sauvegarde `server.crt` et `server.key`** (comme la keystore). Si tu régénères le certificat,
il faudra livrer un nouvel APK contenant le nouveau `server.crt`.

## 6. Nginx

```bash
cp /opt/docswitch/deploy/nginx-docswitch.conf /etc/nginx/sites-available/docswitch
ln -sf /etc/nginx/sites-available/docswitch /etc/nginx/sites-enabled/docswitch
nginx -t && systemctl reload nginx   # reload : les autres sites ne sont pas coupés
```

## 7. Vérifier depuis ton PC

```bash
# Sur le PC, dans le dossier du dépôt :
scp root@185.215.165.43:/etc/nginx/docswitch/server.crt mobile/android/app/src/main/res/raw/docswitch_server.crt

curl --cacert mobile/android/app/src/main/res/raw/docswitch_server.crt https://185.215.165.43:8445/health

# Conversion réelle (remplace CLE par la clé de l'étape 3) :
curl --cacert mobile/android/app/src/main/res/raw/docswitch_server.crt \
  -H "X-API-Key: CLE" -F "file=@un_document.pdf" \
  -o resultat.docx https://185.215.165.43:8445/convert/pdf-to-docx
```

Le `scp` place aussi le certificat là où l'app l'attend.

## 8. Vérifier que rien ne reste sur le serveur

```bash
# Pendant ou après une conversion :
docker exec docswitch-api ls -A /tmp/docswitch-jobs    # doit être vide après chaque requête
docker compose -f /opt/docswitch/deploy/docker-compose.yml logs --tail 20
```

Les journaux ne contiennent que la méthode, la route, le code HTTP et la durée : ni nom de fichier,
ni contenu.

---

## Mettre à jour l'API

```bash
# Sur le PC : renvoyer le code (commande rsync de l'étape 2), puis sur le VPS :
cd /opt/docswitch/deploy && docker compose up -d --build
docker image prune -f
```

## Commandes utiles

| Besoin | Commande |
|---|---|
| Voir les journaux | `docker compose logs -f` (dans `/opt/docswitch/deploy`) |
| Redémarrer | `docker compose restart` |
| Changer la clé d'API | modifier `.env` puis `docker compose up -d` |
| Tests automatiques | `cd /opt/docswitch && docker run --rm -v "$PWD/backend:/src" -w /src -u root docswitch-api sh -c "pip install -q -r requirements-dev.txt && pytest -q"` |

## Passer à un nom de domaine (optionnel)

1. Faire pointer un nom (ex. `api.mondomaine.com`) vers `185.215.165.43`.
2. `apt install -y certbot python3-certbot-nginx`, remplacer `server_name` par le nom dans la
   config Nginx, puis `certbot --nginx -d api.mondomaine.com`.
3. Dans l'app : changer `API_BASE_URL` (`mobile/src/config/app.ts`) et retirer le bloc
   `domain-config` de `network_security_config.xml`. Livrer un nouvel APK.
