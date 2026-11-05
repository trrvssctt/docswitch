# DocSwitch (nom provisoire) — Brief du projet pour Claude Code

## Objectif
Application mobile **Android** qui convertit **PDF → Word (.docx)** et **Word (.docx) → PDF**.
- **Un seul utilisateur**, distribution par **APK signé** installé à la main (pas de Play Store, pas d'iOS).
- Interface **en français**. Pas de compte, pas de paiement, pas de quotas.
- La conversion se fait **côté serveur** (VPS Contabo de l'auteur). L'app mobile est un client léger.

## Stack
- **Mobile** : React Native + TypeScript (Android uniquement). Android Studio sert à l'émulateur, au SDK et au build Gradle.
- **Navigation** : React Navigation. **État** : Zustand ou React Context (rester simple).
- **Fichiers** : `react-native-document-picker`, `react-native-fs` (ou `expo-file-system` si Expo), `react-native-share`, `react-native-blob-util` pour l'upload/téléchargement.
- **Partage entrant** (« Ouvrir avec » / « Partager vers ») : intent filters Android pour `application/pdf` et les types .docx, avec une lib comme `react-native-receive-sharing-intent`.
- **Stockage local** : `@react-native-async-storage/async-storage` pour l'historique et les réglages.
- **Backend** : Python 3.11 + FastAPI, déployé sur le VPS derrière Nginx en HTTPS.
  - PDF → Word : `pdf2docx`.
  - Word → PDF : LibreOffice en mode headless (`soffice --headless --convert-to pdf`).
  - Optionnel plus tard : `ocrmypdf` + Tesseract (fra, ara, eng) pour les PDF scannés.

## Écrans (voir aussi les maquettes Claude Design)
1. Accueil : 2 cartes (PDF → Word, Word → PDF) + 3 conversions récentes.
2. Choix du fichier : picker, nom, taille, bouton « Convertir ».
3. Conversion en cours : progression par étapes, bouton annuler.
4. Résultat : ouvrir, partager, enregistrer dans Téléchargements.
5. Erreurs : fichier trop gros, PDF protégé, hors-ligne, erreur serveur.
6. Historique : liste, ouvrir/partager/supprimer.
7. Paramètres : thème clair/sombre/système, historique, version de l'app.
8. Entrée par partage : l'app s'ouvre avec le fichier déjà chargé et choisit la bonne conversion selon le type.

## Contrat d'API (backend)
Authentification : en-tête `X-API-Key` avec une clé secrète (variable d'environnement côté serveur, saisie dans les paramètres de l'app ou injectée au build via un fichier non versionné).

| Méthode | Route | Corps | Réponse |
|---|---|---|---|
| POST | `/convert/pdf-to-docx` | multipart `file` (.pdf) | 200 : fichier .docx en flux |
| POST | `/convert/docx-to-pdf` | multipart `file` (.docx) | 200 : fichier .pdf en flux |
| GET | `/health` | — | `{"status":"ok","version":"x.y.z"}` |

Codes d'erreur JSON `{"code": "...", "message": "..."}` :
- `FILE_TOO_LARGE` (413) : plus de 50 Mo.
- `INVALID_FILE` (415 ou 422) : mauvais type ou fichier corrompu.
- `PDF_PASSWORD_PROTECTED` (422).
- `CONVERSION_FAILED` (500).
- `UNAUTHORIZED` (401).

Règles serveur :
- Fichiers temporaires dans un dossier unique par requête, **supprimés dès la fin de la réponse** (y compris en cas d'erreur).
- Timeout de conversion : 120 s. Une seule conversion LibreOffice à la fois (verrou), car il n'aime pas les instances parallèles.
- Aucun contenu de document dans les logs.

## Structure de dossiers conseillée
```
/mobile
  /android
  /src
    /screens        (Home, PickFile, Converting, Result, History, Settings)
    /components
    /services       (api.ts, storage.ts, share.ts)
    /store
    /theme
    /utils
  App.tsx
/backend
  main.py
  converters.py
  requirements.txt
  Dockerfile        (python + libreoffice-writer + polices)
```

## Conventions
- TypeScript strict, composants fonctionnels, pas de `any` sans justification.
- Textes de l'interface dans un fichier unique (`strings.fr.ts`) pour éviter le texte en dur.
- Gérer chaque appel réseau avec timeout, annulation et message d'erreur lisible en français.
- Ne jamais commiter la clé d'API ni la keystore.
- Petits commits, un par fonctionnalité.

## Build de l'APK
1. Générer une keystore une fois : `keytool -genkeypair -v -keystore docswitch.keystore -alias docswitch -keyalg RSA -keysize 2048 -validity 10000`. **La sauvegarder en deux endroits : sans elle, aucune mise à jour possible par-dessus l'app installée.**
2. Renseigner la signature dans `android/gradle.properties` (hors dépôt) et `android/app/build.gradle`.
3. Construire : `cd android && ./gradlew assembleRelease`.
4. L'APK se trouve dans `android/app/build/outputs/apk/release/`.
5. Incrémenter `versionCode` et `versionName` à chaque nouvelle version livrée.

## Ordre de travail
1. Backend : `/health`, puis les deux conversions, tests avec 5 vrais documents (dont un tableau, un scan, un texte en arabe).
2. Déploiement sur le VPS (Docker + Nginx + HTTPS), vérification de la suppression des fichiers temporaires.
3. App : navigation et thème, puis choix du fichier, appel API, résultat, partage.
4. Historique et paramètres.
5. Partage entrant (intent filters).
6. Gestion complète des erreurs, tests sur un vrai téléphone Android.
7. Build release signé et livraison de l'APK.

## Critères de réussite
- Conversion d'un PDF texte de 10 pages en moins de 15 secondes avec une connexion correcte.
- Aucun crash sur fichier invalide, protégé ou trop gros : message clair à la place.
- Aucun fichier utilisateur ne reste sur le serveur après la requête.
- Le partage depuis WhatsApp ouvre l'app avec le fichier chargé.
- L'APK s'installe et se met à jour par-dessus la version précédente.
