# M-Motors - Bloc 3 Développer une solution digitale

Application web de gestion de véhicules d’occasion pour l’achat et la location longue durée.

## Stack technique

- Frontend : React, Vite
- Backend : Python, FastAPI
- Base de données : SQLite en local, compatible PostgreSQL via configuration
- Monitoring : endpoint `/health`, `/metrics`, logs applicatifs, configuration Prometheus/Grafana
- Déploiement : Render pour le backend, Vercel pour le frontend

## Fonctionnalités

- Consultation du catalogue véhicules
- Filtrage achat / location
- Authentification utilisateur et administrateur
- Dépôt de dossier dématérialisé
- Upload et téléchargement de documents
- Suivi de dossier client
- Back-office administrateur
- Validation ou refus des dossiers
- Gestion des véhicules
- Monitoring applicatif

## Comptes de test

- Admin : `admin@mmotors.fr` / `Admin123!`
- User : `user@mmotors.fr` / `User123!`

## Lancement local

### Backend

```powershell
cd backend
py -3.12 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

API locale : `http://127.0.0.1:8000/docs`

### Frontend

Sans npm : ouvrir directement `frontend/dist/index.html`.

Le frontend détecte automatiquement :

- local : `http://127.0.0.1:8000`
- production : `https://mmotors-back.onrender.com`


## Correction demandée par l’évaluateur : persistance en production

Le backend est compatible avec PostgreSQL en production. Sur Render, il faut créer une base PostgreSQL puis ajouter la variable d’environnement `DATABASE_URL` dans le service backend. Lorsque cette variable est présente, l’endpoint `/health` retourne `database: postgresql`.

Les justificatifs téléversés ne sont plus stockés uniquement sur le disque local du serveur. Leur contenu binaire est enregistré en base de données dans la table `documents`, ce qui permet aux documents de survivre à un redéploiement Render.

Preuve attendue :

1. créer un compte utilisateur ;
2. déposer un dossier ;
3. ajouter un justificatif PDF ou image ;
4. redéployer le backend Render ;
5. se reconnecter et vérifier que le dossier et le justificatif sont encore présents.

## Déploiement

### Render backend

- Root directory : `backend`
- Build command : `pip install -r requirements.txt`
- Start command : `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Vercel frontend

- Framework : Other
- Root directory : `frontend`
- Install command : `echo skip`
- Build command : `echo skip`
- Output directory : `dist`

## Tests

```powershell
cd backend
venv\Scripts\python.exe -m pytest --cov=app
```
## Captures d’écran

Les captures d’écran de l’application sont disponibles dans le dossier `docs`.